"""Tests Fase 3 — pipeline de resolución mapping → keyword → default."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="Fase 3 — pendiente de implementación")


def test_resolucion_mapping_sobre_keyword(db_conn):
    """Si existe mapping revisado, gana siempre sobre keyword."""


def test_resolucion_keyword_cuando_no_hay_mapping(db_conn):
    pass


def test_resolucion_default_sin_keyword(db_conn):
    pass


def test_resolucion_keyword_persiste_pendiente(db_conn):
    """Cuando entra por keyword, debe quedar en mappings_articulos como pendiente."""


def test_texto_libre_se_guarda_pendiente(db_conn):
    pass


def test_cliente_sin_subcuenta_lanza_error(db_conn):
    pass
