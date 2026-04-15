"""Lectura y escritura CSV para mappings, keywords e historial.

Convenciones:
  - Encoding: UTF-8 con BOM (`utf-8-sig`) para compatibilidad con Excel ES
  - Separador: coma; los campos con comas se entrecomillan automáticamente
  - Importación: NUNCA sobreescribe filas con `revisado=1` (delegado al store)
  - Validación de subcuentas con regex antes de insertar — los errores se
    acumulan en `ResultadoImport.errores` con número de línea para mostrarlos
    en la UI sin abortar el lote completo
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from app.mapping.store import (
    SubcuentaInvalidaError,
    upsert_articulo_mapping,
    upsert_cliente_mapping,
)

log = logging.getLogger(__name__)

ENCODING = 'utf-8-sig'

CLIENTE_FIELDS = (
    'codigo_gesdai', 'nombre', 'nif', 'subcuenta_a3', 'revisado', 'notas',
)
ARTICULO_FIELDS = (
    'clave_gesdai', 'descripcion', 'cuenta_a3', 'es_texto_libre', 'revisado', 'notas',
)
KEYWORD_FIELDS = ('keyword', 'cuenta_a3', 'prioridad', 'activo')
HISTORIAL_FIELDS = (
    'id', 'fecha_export', 'fecha_desde', 'fecha_hasta', 'num_facturas',
    'dat_fichero', 'dat_hash', 'app_version', 'validado',
)


@dataclass
class ResultadoImport:
    """Resumen de un import. `errores` lista mensajes legibles para la UI."""
    insertados: int = 0
    actualizados: int = 0
    saltados_revisados: int = 0
    errores: list[str] = field(default_factory=list)

    @property
    def total_procesados(self) -> int:
        return self.insertados + self.actualizados + self.saltados_revisados


# ─── Mappings de clientes ──────────────────────────────────────────────────


def importar_mappings_clientes(conn: sqlite3.Connection, ruta: Path) -> ResultadoImport:
    resultado = ResultadoImport()
    with open(ruta, encoding=ENCODING, newline='') as fh:
        reader = csv.DictReader(fh)
        _validar_cabeceras(reader.fieldnames, CLIENTE_FIELDS, ruta)
        for nlinea, fila in enumerate(reader, start=2):
            try:
                _importar_fila_cliente(conn, fila, resultado)
            except (SubcuentaInvalidaError, ValueError) as e:
                resultado.errores.append(f"línea {nlinea}: {e}")
    conn.commit()
    return resultado


def _importar_fila_cliente(
    conn: sqlite3.Connection,
    fila: dict[str, str],
    resultado: ResultadoImport,
) -> None:
    codigo = (fila.get('codigo_gesdai') or '').strip()
    if not codigo:
        raise ValueError("codigo_gesdai vacío")
    subcuenta = (fila.get('subcuenta_a3') or '').strip() or None
    outcome = upsert_cliente_mapping(
        conn,
        codigo=codigo,
        nombre=(fila.get('nombre') or '').strip(),
        nif=(fila.get('nif') or '').strip() or None,
        subcuenta_a3=subcuenta,
        notas=(fila.get('notas') or '').strip() or None,
        revisado=_parse_bool(fila.get('revisado')),
    )
    _contar(resultado, outcome)


def exportar_mappings_clientes(conn: sqlite3.Connection, ruta: Path) -> Path:
    rows = conn.execute(
        f"SELECT {', '.join(CLIENTE_FIELDS)} FROM mappings_clientes "
        "ORDER BY codigo_gesdai"
    ).fetchall()
    _escribir_csv(ruta, CLIENTE_FIELDS, rows)
    return ruta


# ─── Mappings de artículos ─────────────────────────────────────────────────


def importar_mappings_articulos(conn: sqlite3.Connection, ruta: Path) -> ResultadoImport:
    resultado = ResultadoImport()
    with open(ruta, encoding=ENCODING, newline='') as fh:
        reader = csv.DictReader(fh)
        _validar_cabeceras(reader.fieldnames, ARTICULO_FIELDS, ruta)
        for nlinea, fila in enumerate(reader, start=2):
            try:
                _importar_fila_articulo(conn, fila, resultado)
            except (SubcuentaInvalidaError, ValueError) as e:
                resultado.errores.append(f"línea {nlinea}: {e}")
    conn.commit()
    return resultado


def _importar_fila_articulo(
    conn: sqlite3.Connection,
    fila: dict[str, str],
    resultado: ResultadoImport,
) -> None:
    clave = (fila.get('clave_gesdai') or '').strip()
    if not clave:
        raise ValueError("clave_gesdai vacía")
    cuenta = (fila.get('cuenta_a3') or '').strip() or None
    # es_texto_libre: None cuando la celda está vacía, para que el UPDATE
    # no sobreescriba el valor existente (COALESCE en el store).
    texto_libre_celda = fila.get('es_texto_libre')
    es_texto_libre = (
        _parse_bool(texto_libre_celda)
        if texto_libre_celda not in (None, '')
        else None
    )
    outcome = upsert_articulo_mapping(
        conn,
        clave=clave,
        descripcion=(fila.get('descripcion') or '').strip() or None,
        cuenta_a3=cuenta,
        es_texto_libre=es_texto_libre,
        notas=(fila.get('notas') or '').strip() or None,
        revisado=_parse_bool(fila.get('revisado')),
    )
    _contar(resultado, outcome)


def exportar_mappings_articulos(conn: sqlite3.Connection, ruta: Path) -> Path:
    rows = conn.execute(
        f"SELECT {', '.join(ARTICULO_FIELDS)} FROM mappings_articulos "
        "ORDER BY clave_gesdai"
    ).fetchall()
    _escribir_csv(ruta, ARTICULO_FIELDS, rows)
    return ruta


# ─── Keywords ──────────────────────────────────────────────────────────────


def importar_keywords(conn: sqlite3.Connection, ruta: Path) -> ResultadoImport:
    from app.mapping.keywords import add_keyword

    resultado = ResultadoImport()
    with open(ruta, encoding=ENCODING, newline='') as fh:
        reader = csv.DictReader(fh)
        _validar_cabeceras(reader.fieldnames, KEYWORD_FIELDS, ruta)
        for nlinea, fila in enumerate(reader, start=2):
            try:
                add_keyword(
                    conn,
                    keyword=(fila.get('keyword') or '').strip(),
                    cuenta_a3=(fila.get('cuenta_a3') or '').strip(),
                    prioridad=int(fila.get('prioridad') or 10),
                    activo=_parse_bool(fila.get('activo'), default=True),
                )
                resultado.insertados += 1
            except (SubcuentaInvalidaError, ValueError) as e:
                resultado.errores.append(f"línea {nlinea}: {e}")
    conn.commit()
    return resultado


def exportar_keywords(conn: sqlite3.Connection, ruta: Path) -> Path:
    rows = conn.execute(
        f"SELECT {', '.join(KEYWORD_FIELDS)} FROM keywords_articulos "
        "ORDER BY prioridad DESC, id ASC"
    ).fetchall()
    _escribir_csv(ruta, KEYWORD_FIELDS, rows)
    return ruta


# ─── Historial ─────────────────────────────────────────────────────────────


def exportar_historial(conn: sqlite3.Connection, ruta: Path) -> Path:
    rows = conn.execute(
        f"SELECT {', '.join(HISTORIAL_FIELDS)} FROM exportaciones "
        "ORDER BY fecha_export DESC"
    ).fetchall()
    _escribir_csv(ruta, HISTORIAL_FIELDS, rows)
    return ruta


# ─── Helpers internos ──────────────────────────────────────────────────────


def _validar_cabeceras(
    encontradas: list[str] | None,
    esperadas: tuple[str, ...],
    ruta: Path,
) -> None:
    if not encontradas:
        raise ValueError(f"{ruta.name}: el CSV no tiene cabecera")
    faltan = [c for c in esperadas if c not in encontradas]
    if faltan:
        raise ValueError(
            f"{ruta.name}: faltan columnas {', '.join(faltan)} "
            f"(esperado: {', '.join(esperadas)})"
        )


def _escribir_csv(
    ruta: Path,
    columnas: tuple[str, ...],
    rows: list,
) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, 'w', encoding=ENCODING, newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(columnas)
        for r in rows:
            writer.writerow([_serializar(r[col]) for col in columnas])


def _serializar(valor: object) -> str:
    """Convierte un valor SQLite a string para CSV. None → '' (no 'None')."""
    if valor is None:
        return ''
    if isinstance(valor, bool):
        return '1' if valor else '0'
    return str(valor)


def _parse_bool(valor: object, default: bool = False) -> bool:
    """Acepta '1', 'true', 'sí', 'si', 'yes', 'x' como verdaderos."""
    if valor is None or valor == '':
        return default
    if isinstance(valor, bool):
        return valor
    return str(valor).strip().lower() in ('1', 'true', 'sí', 'si', 'yes', 'x', 'verdadero')


def _contar(resultado: ResultadoImport, outcome: str) -> None:
    if outcome == 'insertado':
        resultado.insertados += 1
    elif outcome == 'actualizado':
        resultado.actualizados += 1
    elif outcome == 'saltado_revisado':
        resultado.saltados_revisados += 1
