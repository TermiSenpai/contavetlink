"""Tests Fase 1 — sources/dbf_source.py.

Validan que la implementación DBF respeta la interfaz `DataSource`,
que abre los DBFs en READ_ONLY y que los filtros AND/OR funcionan correctamente.
"""
from __future__ import annotations

import pytest

from app.sources import DataSource
from app.sources.dbf_source import DbfNotFoundError, DbfSchemaError, DbfSource


pytestmark = pytest.mark.skip(reason="Fase 1 — pendiente de implementación")


def test_implementa_interfaz_datasource(data_dev_dir):
    src = DbfSource(data_dev_dir)
    assert isinstance(src, DataSource)


def test_apertura_es_read_only(data_dev_dir):
    """Verifica explícitamente que las tablas se abren en READ_ONLY."""


def test_filtro_fecha_entre(data_dev_dir):
    pass


def test_filtro_fecha_y_cliente_and(data_dev_dir):
    pass


def test_filtro_cliente_or(data_dev_dir):
    pass


def test_filtro_anidado_and_or(data_dev_dir):
    pass


def test_rango_sin_resultados_devuelve_lista_vacia(data_dev_dir):
    pass


def test_campos_texto_devueltos_con_strip(data_dev_dir):
    pass


def test_cliente_no_encontrado_lanza_excepcion(data_dev_dir):
    pass


def test_dbf_no_existe_lanza_excepcion_clara():
    with pytest.raises(DbfNotFoundError):
        DbfSource('C:/no-existe-de-verdad')


def test_campo_esperado_ausente_lanza_excepcion(tmp_path):
    with pytest.raises(DbfSchemaError):
        DbfSource(tmp_path)


def test_contabil_se_lee_como_booleano(data_dev_dir):
    pass


def test_ptsbase_cero_devuelto_como_cero(data_dev_dir):
    pass
