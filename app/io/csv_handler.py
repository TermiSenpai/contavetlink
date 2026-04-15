"""Lectura y escritura CSV para mappings, keywords e historial.

Convenciones:
  - Encoding: UTF-8 con BOM (Excel-compatible)
  - Separador: coma; los campos con comas se entrecomillan
  - Importación: NUNCA sobreescribe filas con revisado=1
  - Validación de subcuentas con regex antes de insertar
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ENCODING = 'utf-8-sig'


@dataclass
class ResultadoImport:
    insertados: int
    actualizados: int
    saltados_revisados: int
    errores: list[str]


def importar_mappings_clientes(conn, ruta: Path) -> ResultadoImport:
    """Importa mappings de clientes desde CSV. No toca filas revisado=1."""
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_mappings_clientes(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def importar_mappings_articulos(conn, ruta: Path) -> ResultadoImport:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_mappings_articulos(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def importar_keywords(conn, ruta: Path) -> ResultadoImport:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_keywords(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def exportar_historial(conn, ruta: Path) -> Path:
    raise NotImplementedError("Pendiente de implementar en Fase 2")
