"""Tests Fase 3 — formateo SUENLACE.DAT (longitud, encoding, formato).

Ver Sección 7 de PLAN_DESARROLLO.md para la especificación oficial.
"""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="Fase 3 — pendiente de implementación")


def test_registro_exactamente_254_chars():
    """Cada línea de SUENLACE.DAT debe tener EXACTAMENTE 254 caracteres."""


def test_cuenta_paddea_12_chars():
    """430001 → '430001      ' (espacios a la derecha hasta 12 chars)."""


def test_encoding_cp1252_caracteres_especiales(tmp_path):
    """Caracteres como ñ, á, € deben escribirse en cp1252 sin error."""


def test_preview_no_escribe_fichero(tmp_path):
    pass


def test_exportar_crea_fichero_crlf(tmp_path):
    """El fichero debe usar CRLF (\\r\\n) como fin de línea."""


def test_hash_sha256_reproducible(tmp_path):
    pass


def test_formato_importe_A():
    """12,50€ → '00000000001250' (escala implícita)."""


def test_formato_importe_B():
    """12,50€ → '000000000012.50' (decimal explícito)."""
