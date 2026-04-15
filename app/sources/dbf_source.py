"""Implementación `DataSource` para GESDAI (DBF/FoxPro).

⚠ REGLA INVIOLABLE: los DBF se abren SIEMPRE en READ_ONLY con codepage='cp1252'
y se cierran en `finally`. Cualquier escritura sobre GESDAI es un bug crítico.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.sources.base import (
    Articulo,
    Cliente,
    DataSource,
    Factura,
    Filtros,
)

log = logging.getLogger(__name__)

# Tablas GESDAI requeridas por la herramienta.
TABLA_FACTURAS = 'cfactura'
TABLA_LINEAS = 'lfactura'
TABLA_CLIENTES = 'clientes'
TABLA_MATERIAL = 'material'

# Campos mínimos esperados — se validan al abrir.
CAMPOS_FACTURA = (
    'CODIGO', 'SERIE', 'NUMERO', 'CLIENTE', 'FECHA',
    'TOTBASE', 'TOTCONIVA',
    'PTSBASE1', 'IVA1', 'RECEQUI1',
    'PTSBASE2', 'IVA2', 'RECEQUI2',
    'PTSBASE3', 'IVA3', 'RECEQUI3',
    'RETIRPF', 'CONTABIL',
)
CAMPOS_CLIENTE = ('CODIGO', 'NOMBRE', 'NIF')
CAMPOS_LINEA = ('CODIGO', 'LINEA', 'ARTICULO', 'CANTIDAD', 'PRECIO', 'IVA', 'TOTAL')


class DbfNotFoundError(FileNotFoundError):
    """El fichero DBF no existe en la ruta configurada."""


class DbfLockedError(IOError):
    """El DBF está bloqueado (probablemente GESDAI lo tiene abierto)."""


class DbfSchemaError(ValueError):
    """El DBF no contiene los campos esperados."""


class DbfSource(DataSource):
    """Lee facturas de GESDAI desde un directorio de DBFs."""

    def __init__(self, dbf_path: str | Path) -> None:
        self.dbf_path = Path(dbf_path)
        if not self.dbf_path.exists():
            raise DbfNotFoundError(f"Directorio GESDAI no existe: {self.dbf_path}")
        self._validate_schema()

    def _validate_schema(self) -> None:
        """Comprueba que las tablas necesarias existen y tienen los campos esperados."""
        raise NotImplementedError("Pendiente de implementar en Fase 1")

    @contextmanager
    def _open_table(self, nombre: str) -> Iterator[object]:
        """Context manager que abre una tabla DBF en READ_ONLY y la cierra siempre."""
        raise NotImplementedError("Pendiente de implementar en Fase 1")

    # ─── Interfaz DataSource ────────────────────────────────────────────────

    def get_facturas(self, filtros: Filtros) -> list[Factura]:
        raise NotImplementedError("Pendiente de implementar en Fase 1")

    def get_cliente(self, codigo: str) -> Cliente:
        raise NotImplementedError("Pendiente de implementar en Fase 1")

    def get_clientes(self) -> list[Cliente]:
        raise NotImplementedError("Pendiente de implementar en Fase 1")

    def get_articulos(self) -> list[Articulo]:
        raise NotImplementedError("Pendiente de implementar en Fase 1")
