"""Tests de validación contra la spec oficial SUENLACE.DAT.

Ejecutan sobre un DAT generado y verifican estructura, longitud, encoding
y campos clave por posición. Estos tests son los que NUNCA pueden romperse
sin invalidar el output frente a a3ASESOR.

Spec completa en Sección 7 de PLAN_DESARROLLO.md.
"""
from __future__ import annotations

import pytest

from app.exporter.suenlace import ENCODING, EOL, LONGITUD_REGISTRO


pytestmark = pytest.mark.validation


def test_constantes_spec():
    """Las constantes derivadas del spec no pueden cambiar accidentalmente."""
    assert LONGITUD_REGISTRO == 254
    assert ENCODING == 'cp1252'
    assert EOL == '\r\n'


@pytest.mark.skip(reason="Fase 3 — requiere DAT generado")
def test_todos_los_registros_miden_254_chars(tmp_path):
    pass


@pytest.mark.skip(reason="Fase 3 — requiere DAT generado")
def test_separador_linea_es_crlf(tmp_path):
    pass


@pytest.mark.skip(reason="Fase 3 — requiere DAT generado")
def test_encoding_cp1252(tmp_path):
    pass


@pytest.mark.skip(reason="Fase 3 — requiere DAT generado")
def test_tipreg_en_posicion_15(tmp_path):
    """Posición 15 (1-indexed) debe ser '1' (cabecera) o '9' (detalle)."""


@pytest.mark.skip(reason="Fase 3 — requiere DAT generado")
def test_cuenta_padding_12_chars_en_posicion_16(tmp_path):
    pass
