"""Implementación `DataSource` para GESDAI (DBF/FoxPro).

⚠ REGLA INVIOLABLE: los DBF se abren SIEMPRE en READ_ONLY con codepage='cp1252'
y se cierran en `finally`. Cualquier escritura sobre GESDAI es un bug crítico.

Los campos `CAMPOS_*` se validan en el constructor: si el DBF de COLVET
introduce un cambio de esquema, la app falla rápido con un error descriptivo
en lugar de devolver datos corruptos a las fases siguientes del pipeline.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import dbf as dbf_lib

from app.sources.base import (
    Articulo,
    Cliente,
    DataSource,
    Factura,
    Filtros,
    LineaFactura,
)
from app.sources.filtros import aplica_filtros

log = logging.getLogger(__name__)

# Tablas GESDAI requeridas por la herramienta.
TABLA_FACTURAS = 'cfactura'
TABLA_LINEAS = 'lfactura'
TABLA_CLIENTES = 'clientes'
TABLA_MATERIAL = 'material'

# Campos mínimos esperados — se validan al abrir cada tabla.
CAMPOS_FACTURA = (
    'CODIGO', 'SERIE', 'NUMERO', 'CLIENTE', 'FECHA',
    'TOTPTS', 'TOTCONIVA',
    'PTSBASE1', 'IVA1', 'RECEQUI1',
    'PTSBASE2', 'IVA2', 'RECEQUI2',
    'PTSBASE3', 'IVA3', 'RECEQUI3',
    'RETIRPF', 'CONTABIL',
)
CAMPOS_LINEA = ('CODIGO', 'LINEA', 'ARTICULO', 'COMENTARIO', 'CANTIDAD', 'PRECIOV', 'IVA', 'TOTLINEA')
CAMPOS_CLIENTE = ('CODIGO', 'NOMBRE', 'NIF')
CAMPOS_MATERIAL = ('CLAVEMATE', 'DESCRIPCIO')

_TABLAS_REQUERIDAS = (
    (TABLA_FACTURAS, CAMPOS_FACTURA),
    (TABLA_LINEAS, CAMPOS_LINEA),
    (TABLA_CLIENTES, CAMPOS_CLIENTE),
    (TABLA_MATERIAL, CAMPOS_MATERIAL),
)


class DbfNotFoundError(FileNotFoundError):
    """El directorio o el fichero DBF no existe en la ruta configurada."""


class DbfLockedError(IOError):
    """El DBF está bloqueado (probablemente GESDAI lo tiene abierto)."""


class DbfSchemaError(ValueError):
    """El DBF no contiene los campos esperados o no se pudo abrir."""


class DbfSource(DataSource):
    """Lee facturas de GESDAI desde un directorio de DBFs.

    El path es siempre el directorio que contiene `cfactura.dbf`, `lfactura.dbf`,
    `clientes.dbf` y `material.dbf`. Nunca un fichero suelto.
    """

    def __init__(self, dbf_path: str | Path) -> None:
        self.dbf_path = Path(dbf_path)
        if not self.dbf_path.exists():
            raise DbfNotFoundError(f"Directorio GESDAI no existe: {self.dbf_path}")
        if not self.dbf_path.is_dir():
            raise DbfNotFoundError(
                f"dbf_path debe apuntar a un directorio, no a un fichero: {self.dbf_path}"
            )
        self._validate_schema()

    # ─── Validación e I/O de bajo nivel ────────────────────────────────────

    def _table_path(self, nombre: str) -> Path:
        return self.dbf_path / f"{nombre}.dbf"

    def _validate_schema(self) -> None:
        for nombre, campos in _TABLAS_REQUERIDAS:
            ruta = self._table_path(nombre)
            if not ruta.is_file():
                raise DbfSchemaError(
                    f"Falta tabla obligatoria '{nombre}.dbf' en {self.dbf_path}"
                )
            with self._open_table(nombre) as tabla:
                disponibles = set(tabla.field_names)
                faltan = [c for c in campos if c not in disponibles]
                if faltan:
                    raise DbfSchemaError(
                        f"{nombre}.dbf no contiene los campos requeridos: "
                        f"{', '.join(faltan)}"
                    )

    @contextmanager
    def _open_table(self, nombre: str) -> Iterator[Any]:
        """Abre una tabla DBF en READ_ONLY y garantiza el cierre.

        Encoding fijo a `cp1252`. Cualquier modo distinto de READ_ONLY es un
        bug crítico — esta es la única función que abre tablas en todo el módulo.
        """
        ruta = self._table_path(nombre)
        try:
            tabla = dbf_lib.Table(str(ruta), codepage='cp1252')
            tabla.open(mode=dbf_lib.READ_ONLY)
        except dbf_lib.DbfError as e:
            mensaje = str(e).lower()
            if any(p in mensaje for p in ('lock', 'access', 'permission', 'denied', 'in use')):
                raise DbfLockedError(
                    f"GESDAI parece estar en uso (no se puede leer {ruta.name}). "
                    f"Inténtalo fuera del horario de trabajo."
                ) from e
            raise DbfSchemaError(f"No se pudo abrir {ruta.name}: {e}") from e
        try:
            yield tabla
        finally:
            tabla.close()

    # ─── Interfaz DataSource ────────────────────────────────────────────────

    def get_facturas(self, filtros: Filtros) -> list[Factura]:
        """Devuelve todas las facturas que cumplen el árbol de filtros.

        Estrategia: cargar líneas en memoria (indexadas por código de factura)
        y luego iterar `cfactura` aplicando el filtro factura a factura. Para
        los volúmenes esperados (~552 clientes, ~varios miles de facturas) es
        ampliamente suficiente y mantiene la implementación trivial.

        Saltamos los registros borrados de FoxPro (flag `*`, sin PACK). Las
        facturas con FECHA vacía se incluyen (con `fecha=None`) sólo si su
        NUMERO cae dentro del rango cubierto por las facturas fechadas que
        sí casan con el filtro — así rellenan huecos reales en la secuencia
        ("si entre 200 y 300 falta la 250, se añade") sin contaminar la
        preview con cabeceras incompletas de otros meses.
        """
        lineas_por_factura = self._cargar_lineas()

        con_fecha: list[Factura] = []
        sin_fecha_candidatas: list[Factura] = []
        with self._open_table(TABLA_FACTURAS) as tabla:
            for registro in tabla:
                if dbf_lib.is_deleted(registro):
                    continue
                factura = self._row_to_factura(registro, lineas_por_factura)
                if not aplica_filtros(filtros, factura):
                    continue
                if factura.fecha is None:
                    sin_fecha_candidatas.append(factura)
                else:
                    con_fecha.append(factura)

        if not sin_fecha_candidatas:
            return con_fecha

        rangos = _rangos_numero_por_serie(con_fecha)
        sin_fecha_en_rango = [
            f for f in sin_fecha_candidatas
            if _en_rango(f, rangos)
        ]
        return con_fecha + sin_fecha_en_rango

    def get_cliente(self, codigo: str) -> Cliente:
        with self._open_table(TABLA_CLIENTES) as tabla:
            for registro in tabla:
                if dbf_lib.is_deleted(registro):
                    continue
                if _str(registro['CODIGO']) == codigo:
                    return _row_to_cliente(registro)
        raise KeyError(f"Cliente no encontrado: {codigo}")

    def get_clientes(self) -> list[Cliente]:
        clientes: list[Cliente] = []
        with self._open_table(TABLA_CLIENTES) as tabla:
            for registro in tabla:
                if dbf_lib.is_deleted(registro):
                    continue
                clientes.append(_row_to_cliente(registro))
        return clientes

    def get_articulos(self) -> list[Articulo]:
        articulos: list[Articulo] = []
        with self._open_table(TABLA_MATERIAL) as tabla:
            for registro in tabla:
                if dbf_lib.is_deleted(registro):
                    continue
                articulos.append(
                    Articulo(
                        clave=_str(registro['CLAVEMATE']),
                        descripcion=_str(registro['DESCRIPCIO']) or None,
                    )
                )
        return articulos

    # ─── Helpers internos ──────────────────────────────────────────────────

    def _cargar_lineas(self) -> dict[str, list[LineaFactura]]:
        agrupadas: dict[str, list[LineaFactura]] = {}
        with self._open_table(TABLA_LINEAS) as tabla:
            for registro in tabla:
                if dbf_lib.is_deleted(registro):
                    continue
                linea = LineaFactura(
                    codigo_factura=_str(registro['CODIGO']),
                    linea=int(registro['LINEA'] or 0),
                    articulo=_str(registro['ARTICULO']),
                    cantidad=_dec(registro['CANTIDAD']),
                    precio=_dec(registro['PRECIOV']),
                    iva=_dec(registro['IVA']),
                    total_linea=_dec(registro['TOTLINEA']),
                    comentario=_str(registro['COMENTARIO']),
                )
                agrupadas.setdefault(linea.codigo_factura, []).append(linea)
        for lineas in agrupadas.values():
            lineas.sort(key=lambda lf: lf.linea)
        return agrupadas

    def _row_to_factura(
        self,
        registro: Any,
        lineas_por_factura: dict[str, list[LineaFactura]],
    ) -> Factura:
        """Convierte un registro DBF a `Factura`.

        Las facturas con FECHA vacía se devuelven con `fecha=None`: aparecen
        en la preview con semáforo ROJO para que el contable pueda corregir
        GESDAI, en lugar de ser silenciadas y crear huecos invisibles en la
        secuencia de números.
        """
        codigo = _str(registro['CODIGO'])
        fecha = _fecha_opt(registro['FECHA'])
        if fecha is None:
            log.warning("Factura %s sin FECHA — aparecerá en preview como ROJO", codigo)
        return Factura(
            codigo=codigo,
            serie=_str(registro['SERIE']),
            numero=_str(registro['NUMERO']),
            cliente_codigo=_str(registro['CLIENTE']),
            fecha=fecha,
            total_base=_dec(registro['TOTPTS']),
            total_con_iva=_dec(registro['TOTCONIVA']),
            ptsbase1=_dec(registro['PTSBASE1']),
            iva1=_dec(registro['IVA1']),
            recequi1=_dec(registro['RECEQUI1']),
            ptsbase2=_dec(registro['PTSBASE2']),
            iva2=_dec(registro['IVA2']),
            recequi2=_dec(registro['RECEQUI2']),
            ptsbase3=_dec(registro['PTSBASE3']),
            iva3=_dec(registro['IVA3']),
            recequi3=_dec(registro['RECEQUI3']),
            retirpf=_dec(registro['RETIRPF']),
            contabil=bool(registro['CONTABIL']),
            lineas=lineas_por_factura.get(codigo, []),
        )


# ─── Utilidades de conversión ──────────────────────────────────────────────


def _str(valor: Any) -> str:
    """Convierte un campo de texto DBF a string limpio (sin trailing spaces)."""
    if valor is None:
        return ''
    return str(valor).strip()


def _dec(valor: Any) -> Decimal:
    """Convierte un valor numérico DBF a Decimal. None y vacío → 0."""
    if valor is None or valor == '':
        return Decimal('0')
    if isinstance(valor, Decimal):
        return valor
    return Decimal(str(valor))


def _fecha_opt(valor: Any) -> date | None:
    """Devuelve un `date` o `None` si el campo está vacío.

    Un FECHA vacío (None) NO es fatal — corresponde a una factura mal
    introducida en GESDAI (cabecera creada sin guardar la fecha). El caller
    debe omitir la factura y avisar al operador. Sí lanzamos si el tipo
    es inesperado: eso sería un cambio de esquema de GESDAI y debe parar
    la fase para no propagar datos corruptos al exporter.
    """
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor
    raise DbfSchemaError(f"Tipo inesperado para FECHA: {type(valor).__name__}")


def _row_to_cliente(registro: Any) -> Cliente:
    return Cliente(
        codigo=_str(registro['CODIGO']),
        nombre=_str(registro['NOMBRE']),
        nif=_str(registro['NIF']) or None,
    )


def _rangos_numero_por_serie(
    facturas: list[Factura],
) -> dict[str, tuple[str, str]]:
    """Calcula `{SERIE: (NUMERO_min, NUMERO_max)}` sobre las facturas dadas.

    NUMERO es un string zero-padded en GESDAI ('000338'), así que la comparación
    lexicográfica coincide con la numérica mientras la longitud no varíe — algo
    que el formato fijo de cfactura garantiza.
    """
    rangos: dict[str, tuple[str, str]] = {}
    for f in facturas:
        serie = f.serie.strip()
        numero = f.numero.strip()
        if not numero:
            continue
        actual = rangos.get(serie)
        if actual is None:
            rangos[serie] = (numero, numero)
        else:
            lo, hi = actual
            rangos[serie] = (min(lo, numero), max(hi, numero))
    return rangos


def _en_rango(factura: Factura, rangos: dict[str, tuple[str, str]]) -> bool:
    rango = rangos.get(factura.serie.strip())
    if rango is None:
        return False
    lo, hi = rango
    return lo <= factura.numero.strip() <= hi
