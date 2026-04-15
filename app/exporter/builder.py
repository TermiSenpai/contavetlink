"""Constructor de registros lógicos SUENLACE a partir de facturas resueltas.

Por cada `Factura` produce:
  - 1 registro Cabecera IVA  (tipreg=1)
  - N registros Detalle IVA  (tipreg=9), uno por cada PTSBASE > 0
    El último detalle lleva orden='U', los anteriores 'M'.

Validaciones:
  - sum(bases) + sum(cuotas_iva) ≈ TOTCONIVA   (tolerancia 0,02€)
  - cliente debe tener subcuenta_a3 asignada (else error → 🔴 rojo)
  - factura no puede haber sido exportada antes (else error)
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from app.sources.base import Factura

TOLERANCIA_CUADRE = Decimal('0.02')


class TipoRegistro(str, Enum):
    CABECERA = '1'
    DETALLE = '9'


class OrdenDetalle(str, Enum):
    INTERMEDIO = 'M'
    ULTIMO = 'U'


class OrdenCabecera(str, Enum):
    INICIAL = 'I'


@dataclass
class RegistroCabecera:
    cod_empresa: int
    fecha: str           # AAAAMMDD
    tipreg: TipoRegistro
    cuenta: str          # 12 chars padeados
    descuenta: str       # 30 chars
    numfac: str          # 10 chars
    orden: OrdenCabecera
    desfac: str
    importe: Decimal


@dataclass
class RegistroDetalle:
    cod_empresa: int
    fecha: str
    tipreg: TipoRegistro
    cuenta: str
    descuenta: str
    numfac: str
    orden: OrdenDetalle
    descrip: str
    base: Decimal
    por_iva: Decimal
    cuo_iva: Decimal
    por_rec: Decimal
    cuo_rec: Decimal
    por_ret: Decimal
    cuo_ret: Decimal


class FacturaYaExportadaError(ValueError):
    """La factura ya está registrada en la tabla `exportaciones_detalle`."""


class CuadreError(ValueError):
    """sum(bases) + sum(cuotas) no cuadra con TOTCONIVA dentro de la tolerancia."""


class ClienteSinSubcuentaError(ValueError):
    """El cliente no tiene subcuenta a3ASESOR — bloquea exportación."""


class Builder:
    def __init__(self, conn, resolver, cod_empresa: int) -> None:
        self.conn = conn
        self.resolver = resolver
        self.cod_empresa = cod_empresa

    def construir_registros(
        self,
        factura: Factura,
    ) -> tuple[RegistroCabecera, list[RegistroDetalle]]:
        """Devuelve cabecera + lista de detalles para una factura.

        No escribe nada — solo construye los objetos. La escritura a fichero
        la hace `suenlace.exportar()`.
        """
        raise NotImplementedError("Pendiente de implementar en Fase 3")

    def _validar_cuadre(self, factura: Factura) -> None:
        raise NotImplementedError("Pendiente de implementar en Fase 3")

    def _validar_no_exportada(self, factura: Factura) -> None:
        raise NotImplementedError("Pendiente de implementar en Fase 3")
