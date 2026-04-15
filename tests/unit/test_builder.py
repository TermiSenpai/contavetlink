"""Tests Fase 3 — builder de registros SUENLACE."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="Fase 3 — pendiente de implementación")


def test_factura_un_iva_genera_cabecera_y_un_detalle():
    pass


def test_factura_dos_iva_genera_cabecera_y_dos_detalles():
    pass


def test_ultimo_detalle_orden_U():
    pass


def test_detalles_intermedios_orden_M():
    pass


def test_cuadre_base_mas_iva_tolerancia_002():
    """sum(bases) + sum(cuotas) ≈ TOTCONIVA con tolerancia 0,02€."""


def test_ptsbase_cero_no_genera_detalle():
    pass


def test_cliente_sin_subcuenta_error():
    pass


def test_factura_ya_exportada_error():
    pass
