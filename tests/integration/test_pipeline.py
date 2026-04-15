"""Test de integración Fase 3 — pipeline completo DBF → DAT.

Requiere `tests/data/DATA_DEV/` poblado con DBFs sintéticos.
No corre en CI — solo en local.
"""
from __future__ import annotations

import pytest


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skip(reason="Fase 3 — pendiente de implementación"),
]


def test_flujo_completo_dbf_a_dat(data_dev_dir, tmp_path):
    """DBF sintético → resolver → builder → suenlace → DAT válido."""
