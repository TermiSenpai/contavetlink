"""Tests de integración Fase 4 — endpoints HTTP."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.skip(reason="Fase 4 — pendiente de implementación")


def test_get_config_200(client):
    response = client.get('/config/')
    assert response.status_code == 200


def test_post_config_ruta_invalida_400(client):
    pass


def test_get_mappings_clientes_200(client):
    response = client.get('/mappings/clientes')
    assert response.status_code == 200


def test_post_subcuenta_correcto_200(client):
    pass


def test_post_subcuenta_7_digitos_400(client):
    pass


def test_post_subcuenta_letras_400(client):
    pass


def test_get_preview_sin_filtros_200(client):
    pass


def test_get_preview_con_filtros_and_200(client):
    pass


def test_get_preview_con_filtros_or_200(client):
    pass


def test_post_dat_con_rojo_400(client):
    pass


def test_post_dat_correcto_crea_fichero(client, tmp_path):
    pass


def test_get_historial_200(client):
    response = client.get('/historial/')
    assert response.status_code == 200


def test_import_csv_correcto(client, tmp_path):
    pass


def test_import_csv_invalido_400(client):
    pass


def test_import_excel_correcto(client, tmp_path):
    pass


def test_export_preview_excel(client):
    pass
