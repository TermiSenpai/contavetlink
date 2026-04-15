"""Pipeline de resolución artículo → cuenta contable.

Orden estricto (Sección 6.4 del plan):
    1. mappings_articulos con revisado=1  → tipo='mapping'
    2. keyword matching activo            → tipo='keyword' (guarda pendiente)
    3. cuenta por defecto (config)        → tipo='default'  (marca para revisar)

Nunca devuelve None — siempre hay una cuenta. El tipo permite al semáforo
distinguir verde/amarillo en la UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TipoResolucion(str, Enum):
    MAPPING = 'mapping'
    KEYWORD = 'keyword'
    DEFAULT = 'default'


@dataclass(frozen=True)
class ResolucionArticulo:
    cuenta_a3: str
    tipo: TipoResolucion


class Resolver:
    """Resolución de artículos con dependencias inyectadas (DB + config)."""

    def __init__(self, conn, cuenta_default: str) -> None:
        self.conn = conn
        self.cuenta_default = cuenta_default

    def resolver_articulo(self, clave_articulo: str) -> ResolucionArticulo:
        """Resuelve una clave de artículo a su cuenta contable.

        Aplica el pipeline en orden: mapping → keyword → default.
        Si entra por keyword, persiste el resultado en mappings_articulos
        como pendiente de revisión.
        """
        raise NotImplementedError("Pendiente de implementar en Fase 3")

    def resolver_cliente(self, codigo_cliente: str) -> str:
        """Devuelve la subcuenta 430XXX del cliente.

        Lanza ValueError si el cliente no tiene subcuenta asignada — esto
        produce un 🔴 rojo en el semáforo (bloquea exportación).
        """
        raise NotImplementedError("Pendiente de implementar en Fase 3")
