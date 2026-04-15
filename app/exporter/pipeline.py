"""Orquestación del flujo de exportación: filtros → preview → DAT.

Separa la lógica de negocio de las rutas HTTP. Las rutas llaman a estas
funciones y convierten los resultados a JSON/HTML. Los tests unitarios
atacan directamente este módulo sin pasar por Flask.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.db import (
    SETTING_COD_EMPRESA,
    SETTING_CUENTA_VENTAS_DEF,
    SETTING_EXPORTS_PATH,
    SETTING_IMPORTE_FORMATO,
    get_setting,
)
from app.exporter.builder import Builder
from app.exporter.semaforo import (
    ColorSemaforo,
    EntradaPreview,
    ResumenPreview,
    clasificar_factura,
    resumir,
)
from app.exporter.suenlace import FormatoImporte, exportar
from app.mapping.resolver import Resolver
from app.sources import DataSource
from app.sources.base import (
    Condicion,
    Filtros,
    OperadorCondicion,
    OperadorFiltro,
)

log = logging.getLogger(__name__)


class ConfiguracionIncompletaError(RuntimeError):
    """Falta alguna clave crítica en la tabla `config` del intermediario."""


@dataclass
class PreviewResultado:
    """Lo que la ruta GET/POST /export/preview serializa a JSON."""
    entradas: list[EntradaPreview]
    resumen: ResumenPreview
    advertencias: list[str]


# ─── Serialización del árbol de filtros ───────────────────────────────────


def filtros_desde_json(data: dict[str, Any] | None) -> Filtros:
    """Construye un árbol `Filtros` a partir del JSON que envía el front.

    Formato aceptado (recursivo):
    {
      "operador": "AND" | "OR",
      "condiciones": [
        {"campo": "fecha", "operador": "entre", "valor": ["2026-01-01", "2026-01-31"]},
        {"operador": "OR", "condiciones": [...]}
      ]
    }

    `None` o dict vacío → `Filtros()` (sin condiciones, devuelve todo).
    """
    if not data:
        return Filtros()

    if 'operador' not in data and 'condiciones' not in data:
        return Filtros()

    try:
        op_raw = str(data.get('operador', 'AND')).upper()
        operador = OperadorFiltro(op_raw)
    except ValueError as e:
        raise ValueError(f"Operador de grupo inválido: {data.get('operador')!r}") from e

    items: list[Condicion | Filtros] = []
    for cond in data.get('condiciones') or []:
        if not isinstance(cond, dict):
            raise ValueError(f"Condición no es un objeto: {cond!r}")
        if 'condiciones' in cond or cond.get('tipo') == 'grupo':
            items.append(filtros_desde_json(cond))
        else:
            items.append(_condicion_desde_json(cond))

    return Filtros(operador=operador, condiciones=items)


def _condicion_desde_json(data: dict[str, Any]) -> Condicion:
    campo = data.get('campo')
    operador_raw = data.get('operador')
    valor = data.get('valor')
    if not campo or operador_raw is None:
        raise ValueError(f"Condición incompleta: {data!r}")
    try:
        operador = OperadorCondicion(str(operador_raw))
    except ValueError as e:
        raise ValueError(f"Operador de condición inválido: {operador_raw!r}") from e
    return Condicion(campo=str(campo), operador=operador, valor=valor)


# ─── Filtro por defecto "Mes actual" ──────────────────────────────────────


def filtro_mes_actual(hoy: date | None = None) -> Filtros:
    """Devuelve un filtro `fecha ENTRE primer día — último día del mes en curso`.

    Es el preset de la landing `/export/` para que al abrir la app el operador
    vea de entrada lo que suele necesitar.
    """
    if hoy is None:
        hoy = date.today()
    primer_dia = hoy.replace(day=1)
    # último día: restar 1 día al primer día del mes siguiente
    if hoy.month == 12:
        primer_dia_siguiente = date(hoy.year + 1, 1, 1)
    else:
        primer_dia_siguiente = date(hoy.year, hoy.month + 1, 1)
    from datetime import timedelta
    ultimo_dia = primer_dia_siguiente - timedelta(days=1)
    return Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion(
                campo='fecha',
                operador=OperadorCondicion.ENTRE,
                valor=(primer_dia.isoformat(), ultimo_dia.isoformat()),
            ),
        ],
    )


# ─── Configuración helpers ────────────────────────────────────────────────


@dataclass(frozen=True)
class ConfiguracionExport:
    cod_empresa: int
    cuenta_ventas_def: str
    importe_formato: FormatoImporte
    exports_path: Path


def leer_configuracion(conn: sqlite3.Connection) -> ConfiguracionExport:
    """Lee las claves críticas de `config`. Lanza `ConfiguracionIncompletaError`
    con mensaje claro si falta alguna."""
    faltantes: list[str] = []

    cod_raw = get_setting(conn, SETTING_COD_EMPRESA)
    cuenta = get_setting(conn, SETTING_CUENTA_VENTAS_DEF)
    formato_raw = get_setting(conn, SETTING_IMPORTE_FORMATO)
    exports_raw = get_setting(conn, SETTING_EXPORTS_PATH)

    if cod_raw is None:
        faltantes.append('cod_empresa')
    if cuenta is None:
        faltantes.append('cuenta_ventas_def')
    if formato_raw is None:
        faltantes.append('importe_formato')
    if exports_raw is None:
        faltantes.append('exports_path')

    if faltantes:
        raise ConfiguracionIncompletaError(
            f"Faltan claves en /config/: {', '.join(faltantes)}. "
            f"Ve a /config/ para completar la configuración."
        )

    try:
        cod_empresa = int(cod_raw)  # type: ignore[arg-type]
    except ValueError as e:
        raise ConfiguracionIncompletaError(
            f"cod_empresa no numérico: {cod_raw!r}"
        ) from e

    try:
        formato = FormatoImporte(formato_raw)
    except ValueError as e:
        raise ConfiguracionIncompletaError(
            f"importe_formato inválido: {formato_raw!r} (debe ser 'A' o 'B')"
        ) from e

    return ConfiguracionExport(
        cod_empresa=cod_empresa,
        cuenta_ventas_def=cuenta,  # type: ignore[arg-type]
        importe_formato=formato,
        exports_path=Path(exports_raw),  # type: ignore[arg-type]
    )


# ─── Generar preview ──────────────────────────────────────────────────────


def ejecutar_preview(
    conn: sqlite3.Connection,
    source: DataSource,
    filtros: Filtros,
    config: ConfiguracionExport,
) -> PreviewResultado:
    """Aplica filtros, clasifica cada factura y devuelve la preview completa.

    No escribe ningún fichero. Las rutas HTTP llaman a este servicio para
    popular la tabla del semáforo.
    """
    advertencias: list[str] = []
    resolver = Resolver(conn, cuenta_default=config.cuenta_ventas_def)
    builder = Builder(
        conn,
        resolver=resolver,
        cod_empresa=config.cod_empresa,
        cuenta_ventas_def=config.cuenta_ventas_def,
    )

    facturas = source.get_facturas(filtros)
    entradas = [
        clasificar_factura(f, builder, conn, resolver)
        for f in facturas
    ]

    # Filtro post-clasificación por color (el árbol de filtros no sabe de
    # resolución — `aplica_filtros` devuelve True para condiciones sobre
    # "resolucion"; aquí aplicamos la restricción real si viene).
    color_requerido = _extraer_filtro_resolucion(filtros)
    if color_requerido:
        entradas = [e for e in entradas if e.color.value == color_requerido]

    resumen = resumir(entradas)
    return PreviewResultado(
        entradas=entradas,
        resumen=resumen,
        advertencias=advertencias,
    )


def _extraer_filtro_resolucion(filtros: Filtros) -> str | None:
    """Busca recursivamente un `Condicion(campo='resolucion', IGUAL, valor)`
    en el árbol. Si hay más de uno, gana el primero encontrado en
    profundidad — no es un query builder, es un panel sencillo.
    """
    for item in filtros.condiciones:
        if (
            isinstance(item, Condicion)
            and item.campo == 'resolucion'
            and item.operador == OperadorCondicion.IGUAL
        ):
            return str(item.valor)
        if isinstance(item, Filtros):
            anidado = _extraer_filtro_resolucion(item)
            if anidado:
                return anidado
    return None


# ─── Generar DAT ──────────────────────────────────────────────────────────


@dataclass
class ResultadoGeneracion:
    ruta_dat: Path
    sha256: str
    num_facturas: int
    exportacion_id: int


def ejecutar_generacion(
    conn: sqlite3.Connection,
    source: DataSource,
    filtros: Filtros,
    config: ConfiguracionExport,
    app_version: str,
) -> ResultadoGeneracion:
    """Construye el DAT y lo registra en `exportaciones` + `exportaciones_detalle`.

    Reglas:
      - Las facturas gris (ya exportadas) se excluyen silenciosamente.
      - Cualquier factura roja en el resultado del preview hace fallar con
        `ValueError` ANTES de tocar el disco — el caller traduce a HTTP 400.
      - El commit es atómico: si algo falla tras escribir el DAT, se borra
        el fichero y se hace rollback.
    """
    preview = ejecutar_preview(conn, source, filtros, config)

    rojos = [e for e in preview.entradas if e.color == ColorSemaforo.ROJO]
    if rojos:
        raise ValueError(
            f"No se puede generar el DAT: {len(rojos)} facturas en rojo. "
            f"Corrige los mappings y vuelve a previsualizar."
        )

    exportables = [e for e in preview.entradas if e.exportable]
    if not exportables:
        raise ValueError("Ninguna factura para exportar en el rango seleccionado.")

    cabeceras_y_detalles = [
        (e.construccion.cabecera, e.construccion.detalles)
        for e in exportables
        if e.construccion is not None
    ]

    # Nombre del fichero DAT: SUENLACE_YYYYMMDD_HHMMSS.DAT (evita colisiones)
    ahora = datetime.now(UTC).astimezone()
    nombre = f"SUENLACE_{ahora.strftime('%Y%m%d_%H%M%S')}.DAT"
    ruta_dat = config.exports_path / nombre

    ruta_final, sha = exportar(
        cabeceras_y_detalles, ruta_dat, config.importe_formato,
    )

    # Registro en BD — transacción atómica con rollback si falla
    try:
        rango = _calcular_rango_fechas(exportables)
        cur = conn.execute(
            """
            INSERT INTO exportaciones
                (fecha_export, fecha_desde, fecha_hasta, filtros_json,
                 num_facturas, dat_fichero, dat_hash, app_version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ahora.strftime('%Y-%m-%dT%H:%M:%S'),
                rango[0].isoformat(),
                rango[1].isoformat(),
                json.dumps(_filtros_a_dict(filtros)),
                len(exportables),
                str(ruta_final),
                sha,
                app_version,
            ),
        )
        exportacion_id = int(cur.lastrowid)

        for entrada in exportables:
            cabecera = entrada.construccion.cabecera  # type: ignore[union-attr]
            tipos = [
                r.tipo.value for r in entrada.construccion.tipos_resolucion  # type: ignore[union-attr]
            ]
            tipo_global = 'mapping' if tipos and all(t == 'mapping' for t in tipos) else (
                'keyword' if 'keyword' in tipos else 'default'
            )
            conn.execute(
                """
                INSERT INTO exportaciones_detalle
                    (exportacion_id, codigo_factura, cliente_gesdai,
                     subcuenta_a3, total_coniva, resolucion_tipo)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    exportacion_id,
                    entrada.factura.codigo,
                    entrada.factura.cliente_codigo,
                    cabecera.cuenta.strip(),
                    float(entrada.factura.total_con_iva),
                    tipo_global,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        # No dejamos el .DAT huérfano si el registro falla
        try:
            ruta_final.unlink(missing_ok=True)
        except OSError:
            log.exception("No se pudo borrar DAT huérfano tras rollback: %s", ruta_final)
        raise

    log.info(
        "Exportación generada",
        extra={
            'action': 'dat_generated',
            'exportacion_id': exportacion_id,
            'num_facturas': len(exportables),
            'dat_fichero': str(ruta_final),
            'sha256': sha,
        },
    )

    return ResultadoGeneracion(
        ruta_dat=ruta_final,
        sha256=sha,
        num_facturas=len(exportables),
        exportacion_id=exportacion_id,
    )


def _calcular_rango_fechas(entradas: list[EntradaPreview]) -> tuple[date, date]:
    fechas = [e.factura.fecha for e in entradas]
    return min(fechas), max(fechas)


def _filtros_a_dict(filtros: Filtros) -> dict[str, Any]:
    """Serializa un árbol `Filtros` a dict JSON-safe para persistir en BD."""
    return {
        'operador': filtros.operador.value,
        'condiciones': [_item_a_dict(item) for item in filtros.condiciones],
    }


def _item_a_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, Filtros):
        return _filtros_a_dict(item)
    if isinstance(item, Condicion):
        return {
            'campo': item.campo,
            'operador': item.operador.value,
            'valor': _valor_a_json(item.valor),
        }
    raise TypeError(f"Item de filtro no serializable: {item!r}")


def _valor_a_json(valor: Any) -> Any:
    if isinstance(valor, list | tuple):
        return [_valor_a_json(v) for v in valor]
    if isinstance(valor, date | datetime):
        return valor.isoformat()
    if isinstance(valor, Decimal):
        return str(valor)
    return valor


# ─── Serialización de preview para JSON ───────────────────────────────────


def preview_a_dict(preview: PreviewResultado) -> dict[str, Any]:
    """Convierte un `PreviewResultado` a dict JSON-safe para el front."""
    importe_total = sum(
        (e.factura.total_con_iva for e in preview.entradas if e.exportable),
        Decimal('0'),
    )
    return {
        'resumen': {
            'total': preview.resumen.total,
            'verdes': preview.resumen.verdes,
            'amarillos': preview.resumen.amarillos,
            'rojos': preview.resumen.rojos,
            'grises': preview.resumen.grises,
            'exportables': preview.resumen.verdes + preview.resumen.amarillos,
            'importe_total': str(importe_total),
        },
        'facturas': [_entrada_a_dict(e) for e in preview.entradas],
        'advertencias': preview.advertencias,
    }


def _entrada_a_dict(entrada: EntradaPreview) -> dict[str, Any]:
    subcuenta = ''
    if entrada.construccion is not None:
        subcuenta = entrada.construccion.cabecera.cuenta.strip()
    return {
        'codigo': entrada.factura.codigo,
        'fecha': entrada.factura.fecha.isoformat(),
        'cliente_codigo': entrada.factura.cliente_codigo,
        'serie': entrada.factura.serie.strip(),
        'numero': entrada.factura.numero.strip(),
        'subcuenta': subcuenta,
        'total': str(entrada.factura.total_con_iva),
        'semaforo': entrada.color.value,
        'mensaje': entrada.mensaje,
        'advertencia_contabil': entrada.advertencia_contabil,
        'errores': list(entrada.errores),
        'exportable': entrada.exportable,
    }


def sha256_of_file(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    'ColorSemaforo',
    'ConfiguracionExport',
    'ConfiguracionIncompletaError',
    'PreviewResultado',
    'ResultadoGeneracion',
    'ejecutar_generacion',
    'ejecutar_preview',
    'filtros_desde_json',
    'filtro_mes_actual',
    'leer_configuracion',
    'preview_a_dict',
]
