"""Motor de keyword matching para resolución automática de artículos.

Coincide texto libre de líneas de factura contra una lista de keywords
(case-insensitive) ordenadas por prioridad descendente. La primera coincidencia
gana — el orden de prioridad lo controla el usuario en la UI.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Keyword:
    id: int
    keyword: str
    cuenta_a3: str
    prioridad: int
    activo: bool


def match(texto: str, keywords: list[Keyword]) -> Keyword | None:
    """Devuelve la primera keyword (por prioridad DESC) que matchea `texto`.

    - Case-insensitive
    - Substring match (no regex en v1.0)
    - Solo considera keywords con activo=True
    - Devuelve None si no hay match
    """
    raise NotImplementedError("Pendiente de implementar en Fase 2")


def load_keywords(conn) -> list[Keyword]:
    """Carga keywords activas de la BD ordenadas por prioridad DESC."""
    raise NotImplementedError("Pendiente de implementar en Fase 2")
