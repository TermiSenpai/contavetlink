"""Tests unitarios del clasificador de semáforo.

Sólo cubren ramas autónomas que no necesitan resolver/builder reales
(p.ej. fecha vacía corta antes de tocar nada). El resto de combinaciones
verde/amarillo/rojo viven en los tests de integración con BD.
"""
from __future__ import annotations

from decimal import Decimal

from app.exporter.semaforo import ColorSemaforo, clasificar_factura
from app.sources.base import Factura


def _factura_sin_fecha() -> Factura:
    return Factura(
        codigo='2026000195', serie='2026', numero='000195',
        cliente_codigo='CLI00001', fecha=None,
        total_base=Decimal('100'), total_con_iva=Decimal('121'),
        ptsbase1=Decimal('100'), iva1=Decimal('21'), recequi1=Decimal('0'),
        ptsbase2=Decimal('0'), iva2=Decimal('0'), recequi2=Decimal('0'),
        ptsbase3=Decimal('0'), iva3=Decimal('0'), recequi3=Decimal('0'),
        retirpf=Decimal('0'), contabil=False,
    )


def test_factura_sin_fecha_es_rojo_sin_tocar_builder():
    """Si el clasificador llegase al builder con fecha=None, éste reventaría
    en `factura.fecha.strftime`. Esta rama corta antes para que la preview
    pueda mostrar la factura como ROJO y el contable corrija GESDAI."""

    class BuilderQueRevienta:
        def _validar_no_exportada(self, factura):  # noqa: D401
            raise AssertionError("No debe llamarse cuando fecha es None")

        def construir_registros(self, factura):
            raise AssertionError("No debe llamarse cuando fecha es None")

    entrada = clasificar_factura(
        _factura_sin_fecha(),
        builder=BuilderQueRevienta(),
        conn=None,
        resolver=None,
    )

    assert entrada.color == ColorSemaforo.ROJO
    assert 'FECHA' in entrada.mensaje
    assert entrada.errores  # al menos un error registrado
    assert entrada.construccion is None
    assert entrada.exportable is False
