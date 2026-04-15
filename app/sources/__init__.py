"""Capa de fuentes de datos.

Toda fuente implementa la interfaz `DataSource` definida en `base.py`.
La lógica de negocio NUNCA importa una implementación concreta — solo `base`.
"""
from __future__ import annotations

import sqlite3

from app.sources.base import (
    Articulo,
    Cliente,
    Condicion,
    DataSource,
    Factura,
    Filtros,
    LineaFactura,
    OperadorFiltro,
)


class FuenteNoConfiguradaError(RuntimeError):
    """`dbf_path` no está configurado en la tabla `config` del intermediario."""


def get_configured_source(conn: sqlite3.Connection) -> DataSource:
    """Devuelve una `DataSource` construida con la ruta de `config.dbf_path`.

    Factory única — routes, sync, builder, etc. pasan por aquí para obtener
    la fuente. Si mañana aparece `excel_source.py` o `csv_source.py`, un
    segundo setting `fuente_tipo` decide cuál instanciar y el resto de la
    app no cambia.

    Lanza `FuenteNoConfiguradaError` si no hay ruta (situación típica en el
    primer arranque — la UI debe redirigir a /config/).
    """
    from app.db import SETTING_DBF_PATH, get_setting
    from app.sources.dbf_source import DbfSource

    ruta = get_setting(conn, SETTING_DBF_PATH)
    if not ruta:
        raise FuenteNoConfiguradaError(
            "No hay ruta de GESDAI configurada. "
            "Ve a /config/ para establecerla antes de continuar."
        )
    return DbfSource(ruta)


__all__ = [
    'Articulo',
    'Cliente',
    'Condicion',
    'DataSource',
    'Factura',
    'FuenteNoConfiguradaError',
    'Filtros',
    'LineaFactura',
    'OperadorFiltro',
    'get_configured_source',
]
