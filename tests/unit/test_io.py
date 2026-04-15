"""Tests Fase 2 — import/export CSV y Excel."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="Fase 2 — pendiente de implementación")


def test_init_idempotente(db_conn):
    """Inicializar mappings dos veces no debe sobreescribir filas revisadas."""


def test_set_subcuenta_6_digitos_validos(db_conn):
    pass


def test_set_subcuenta_7_digitos_error(db_conn):
    pass


def test_set_subcuenta_letras_error(db_conn):
    pass


def test_marcar_revisado(db_conn):
    pass


def test_importar_csv_carga_masiva(db_conn, tmp_path):
    pass


def test_importar_csv_no_sobreescribe_revisados(db_conn, tmp_path):
    pass


def test_importar_excel_carga_masiva(db_conn, tmp_path):
    pass


def test_exportar_csv_round_trip(db_conn, tmp_path):
    """Exportar a CSV → importar de vuelta → datos idénticos."""


def test_exportar_excel_round_trip(db_conn, tmp_path):
    pass
