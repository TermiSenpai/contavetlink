"""Sincronización del intermediario con una `DataSource`.

Vuelca los catálogos de clientes y artículos de la fuente al SQLite del
intermediario, **sin sobreescribir nunca filas con `revisado=1`**. Es la
"init idempotente" que el plan exige: ejecutarla N veces converge al estado
correcto y nunca pierde trabajo del operador.

Casos por fila:

  - Nueva → INSERT con `subcuenta_a3=NULL`, `revisado=0`
  - Existente, revisado=0 → UPDATE de nombre/nif (refresca metadatos)
  - Existente, revisado=1 → SKIP (no se toca nada)

El módulo no importa `dbf_source` directamente — solo el contrato `DataSource`
de `sources/base.py`, así que sirve igual para futuras fuentes Excel/CSV.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.mapping.store import (
    get_articulo_mapping,
    get_cliente_mapping,
    upsert_articulo_desde_modelo,
    upsert_cliente_desde_modelo,
)
from app.sources.base import DataSource

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Resumen de una operación de sincronización."""
    insertados: int = 0
    actualizados: int = 0
    saltados_revisados: int = 0

    @property
    def total(self) -> int:
        return self.insertados + self.actualizados + self.saltados_revisados


def sync_clientes(conn: sqlite3.Connection, source: DataSource) -> SyncResult:
    """Vuelca clientes de la fuente. Commitea al final."""
    resultado = SyncResult()
    for cliente in source.get_clientes():
        outcome = upsert_cliente_desde_modelo(conn, cliente)
        _contar(resultado, outcome)
    conn.commit()
    log.info(
        "sync_clientes: %d insertados, %d actualizados, %d revisados saltados",
        resultado.insertados, resultado.actualizados, resultado.saltados_revisados,
        extra={'action': 'sync_clientes', **resultado.__dict__},
    )
    return resultado


def sync_articulos(conn: sqlite3.Connection, source: DataSource) -> SyncResult:
    """Vuelca artículos del catálogo de la fuente. Commitea al final."""
    resultado = SyncResult()
    for articulo in source.get_articulos():
        outcome = upsert_articulo_desde_modelo(conn, articulo)
        _contar(resultado, outcome)
    conn.commit()
    log.info(
        "sync_articulos: %d insertados, %d actualizados, %d revisados saltados",
        resultado.insertados, resultado.actualizados, resultado.saltados_revisados,
        extra={'action': 'sync_articulos', **resultado.__dict__},
    )
    return resultado


def _contar(resultado: SyncResult, outcome: str) -> None:
    if outcome == 'insertado':
        resultado.insertados += 1
    elif outcome == 'actualizado':
        resultado.actualizados += 1
    elif outcome == 'saltado_revisado':
        resultado.saltados_revisados += 1
    else:
        raise ValueError(f"Outcome desconocido del store: {outcome!r}")


# Re-export para que las rutas/tests puedan introspeccionar sin tocar el store.
__all__ = ['SyncResult', 'sync_clientes', 'sync_articulos', 'get_cliente_mapping', 'get_articulo_mapping']
