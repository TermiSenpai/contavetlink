"""Capa de fuentes de datos.

Toda fuente implementa la interfaz `DataSource` definida en `base.py`.
La lógica de negocio NUNCA importa una implementación concreta — solo `base`.
"""
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

__all__ = [
    'Articulo',
    'Cliente',
    'Condicion',
    'DataSource',
    'Factura',
    'Filtros',
    'LineaFactura',
    'OperadorFiltro',
]
