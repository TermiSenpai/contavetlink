"""Lectura y escritura Excel (.xlsx) usando openpyxl.

Cobertura v1.0:
  - Import/Export de mappings_clientes
  - Import/Export de mappings_articulos
  - Export de previews de exportación (para revisión externa)
  - Export del historial
"""
from __future__ import annotations

from pathlib import Path

from app.io.csv_handler import ResultadoImport


def importar_mappings_clientes(conn, ruta: Path) -> ResultadoImport:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_mappings_clientes(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def importar_mappings_articulos(conn, ruta: Path) -> ResultadoImport:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_mappings_articulos(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_preview(facturas_resueltas: list[dict], ruta: Path) -> Path:
    """Exporta una vista previa de exportación con su semáforo a Excel."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


def exportar_historial(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")
