"""Interfaz abstracta `DataSource` y modelos de dominio comunes.

Toda fuente de datos (GESDAI DBF, Excel, CSV, ...) implementa esta interfaz.
Los modelos son los únicos tipos que viajan entre capas — `mapping/`, `exporter/`,
`routes/` SOLO conocen estas dataclasses, nunca tipos específicos de la fuente.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Union

# ─── Modelos de dominio ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class Cliente:
    codigo: str
    nombre: str
    nif: str | None = None
    razon_social: str | None = None


@dataclass(frozen=True)
class Articulo:
    clave: str
    descripcion: str | None = None


@dataclass(frozen=True)
class LineaFactura:
    codigo_factura: str
    linea: int
    articulo: str        # clave del catálogo (puede estar vacía si es texto libre)
    cantidad: Decimal
    precio: Decimal
    iva: Decimal
    total_linea: Decimal
    comentario: str = ''  # descripción libre (campo COMENTARIO en lfactura)


@dataclass
class Factura:
    codigo: str
    serie: str
    numero: str
    cliente_codigo: str
    # `None` cuando la cabecera de GESDAI no tiene FECHA — la factura sigue
    # apareciendo en la preview (ROJO, bloquea exportación) para que el contable
    # la corrija. Solo el flujo de generación de DAT exige fecha real.
    fecha: date | None
    total_base: Decimal
    total_con_iva: Decimal
    ptsbase1: Decimal
    iva1: Decimal
    recequi1: Decimal
    ptsbase2: Decimal
    iva2: Decimal
    recequi2: Decimal
    ptsbase3: Decimal
    iva3: Decimal
    recequi3: Decimal
    retirpf: Decimal
    contabil: bool       # informativo — nunca se escribe en GESDAI
    lineas: list[LineaFactura] = field(default_factory=list)
    fuente: str = 'gesdai_dbf'


# ─── Filtros AND/OR ─────────────────────────────────────────────────────────


class OperadorFiltro(str, Enum):
    AND = 'AND'
    OR = 'OR'


class OperadorCondicion(str, Enum):
    IGUAL = 'igual'
    NO_IGUAL = 'no_igual'
    CONTIENE = 'contiene'
    ENTRE = 'entre'
    ANTES_DE = 'antes_de'
    DESPUES_DE = 'despues_de'
    MAYOR_QUE = 'mayor_que'
    MENOR_QUE = 'menor_que'


@dataclass
class Condicion:
    campo: str            # 'fecha', 'cliente', 'serie', 'resolucion', 'importe'
    operador: OperadorCondicion
    valor: object


# Recursivo: un Filtros puede contener Condiciones y otros Filtros.
ItemFiltro = Union[Condicion, "Filtros"]


@dataclass
class Filtros:
    operador: OperadorFiltro = OperadorFiltro.AND
    condiciones: list[ItemFiltro] = field(default_factory=list)


# ─── Interfaz abstracta ─────────────────────────────────────────────────────


class DataSource(ABC):
    """Contrato que toda fuente de datos debe implementar.

    Las implementaciones deben:
      - Abrir los recursos en modo lectura (READ_ONLY) — nunca escribir.
      - Cerrar handles en `finally` o usando context managers.
      - Validar la presencia de campos esperados al abrir y lanzar excepciones
        descriptivas si falta alguno.
    """

    @abstractmethod
    def get_facturas(self, filtros: Filtros) -> list[Factura]:
        """Devuelve facturas que cumplen el árbol de filtros."""

    @abstractmethod
    def get_cliente(self, codigo: str) -> Cliente:
        """Devuelve un cliente por código. Lanza KeyError si no existe."""

    @abstractmethod
    def get_clientes(self) -> list[Cliente]:
        """Devuelve la lista completa de clientes."""

    @abstractmethod
    def get_articulos(self) -> list[Articulo]:
        """Devuelve la lista de artículos del catálogo."""
