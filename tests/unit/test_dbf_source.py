"""Tests Fase 1 — sources/dbf_source.py.

Validan que la implementación DBF respeta la interfaz `DataSource`, abre los
DBFs en READ_ONLY y filtra correctamente. Los tests con `data_dev_dir` se
saltan automáticamente si el directorio no existe (ver `tests/conftest.py`).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import dbf as dbf_lib
import pytest

from app.sources import DataSource
from app.sources.base import (
    Cliente,
    Condicion,
    Factura,
    Filtros,
    LineaFactura,
    OperadorCondicion,
    OperadorFiltro,
)
from app.sources.dbf_source import (
    DbfNotFoundError,
    DbfSchemaError,
    DbfSource,
)

# ─── Errores de apertura y validación de esquema ───────────────────────────


def test_root_route_redirige_a_export(client):
    """`/` debe redirigir a /export/ — sin esto el dev server muestra 404 al abrir."""
    resp = client.get('/')
    assert resp.status_code in (301, 302, 308)
    assert '/export' in resp.headers['Location']


@pytest.mark.parametrize('ruta', [
    '/config/',
    '/export/',
    '/mappings/clientes',
    '/mappings/articulos',
    '/keywords/',
    '/historial/',
])
def test_paginas_ui_renderizan_sin_error(client, ruta):
    """Cada página de la UI debe renderizar 200 con su template intacto.

    Bloquea regresiones del tipo "el route GET no pasa los vars que el
    template necesita" — un fallo así rompe el dev server al primer click.
    """
    resp = client.get(ruta)
    assert resp.status_code == 200, f"{ruta} devolvió {resp.status_code}"


def test_dbf_no_existe_lanza_excepcion_clara():
    with pytest.raises(DbfNotFoundError):
        DbfSource('C:/no-existe-de-verdad-xyz')


def test_path_apunta_a_fichero_lanza_error(tmp_path):
    fichero = tmp_path / 'algo.dbf'
    fichero.write_text('contenido')
    with pytest.raises(DbfNotFoundError, match='directorio'):
        DbfSource(fichero)


def test_directorio_vacio_lanza_dbf_schema_error(tmp_path):
    with pytest.raises(DbfSchemaError, match='cfactura.dbf'):
        DbfSource(tmp_path)


# ─── Lectura básica con DATA_DEV ───────────────────────────────────────────


def test_implementa_interfaz_datasource(data_dev_dir):
    src = DbfSource(data_dev_dir)
    assert isinstance(src, DataSource)


def test_get_clientes_devuelve_lista_no_vacia(data_dev_dir):
    src = DbfSource(data_dev_dir)
    clientes = src.get_clientes()
    assert len(clientes) > 0
    assert all(isinstance(c, Cliente) for c in clientes)


def test_get_articulos_devuelve_lista_no_vacia(data_dev_dir):
    src = DbfSource(data_dev_dir)
    articulos = src.get_articulos()
    assert len(articulos) > 0
    assert all(a.clave for a in articulos)


def test_get_cliente_existente(data_dev_dir):
    src = DbfSource(data_dev_dir)
    primer = src.get_clientes()[0]
    encontrado = src.get_cliente(primer.codigo)
    assert encontrado.codigo == primer.codigo
    assert encontrado.nombre == primer.nombre


def test_get_cliente_no_encontrado_lanza_key_error(data_dev_dir):
    src = DbfSource(data_dev_dir)
    with pytest.raises(KeyError, match='Cliente no encontrado'):
        src.get_cliente('CLI99999')


def test_get_facturas_sin_filtros_devuelve_todas(data_dev_dir):
    src = DbfSource(data_dev_dir)
    facturas = src.get_facturas(Filtros())
    assert len(facturas) > 0
    f = facturas[0]
    assert isinstance(f, Factura)
    assert isinstance(f.fecha, date)
    assert isinstance(f.total_con_iva, Decimal)


# ─── Garantías sobre los datos cargados ────────────────────────────────────


def test_campos_texto_devueltos_sin_trailing_spaces(data_dev_dir):
    src = DbfSource(data_dev_dir)
    cliente = src.get_clientes()[0]
    assert cliente.codigo == cliente.codigo.strip()
    assert cliente.nombre == cliente.nombre.strip()


def test_contabil_se_lee_como_booleano(data_dev_dir):
    src = DbfSource(data_dev_dir)
    factura = src.get_facturas(Filtros())[0]
    assert isinstance(factura.contabil, bool)


def test_ptsbase_y_retirpf_son_decimal(data_dev_dir):
    """Los importes deben ser Decimal — nunca float — para evitar errores
    de redondeo en el motor contable."""
    src = DbfSource(data_dev_dir)
    facturas = src.get_facturas(Filtros())
    for f in facturas[:5]:
        for atributo in ('ptsbase1', 'ptsbase2', 'ptsbase3', 'iva1', 'retirpf'):
            assert isinstance(getattr(f, atributo), Decimal), atributo


def test_lineas_se_asocian_a_su_factura(data_dev_dir):
    src = DbfSource(data_dev_dir)
    facturas = src.get_facturas(Filtros())
    con_lineas = [f for f in facturas if f.lineas]
    assert con_lineas, "DATA_DEV no tiene facturas con líneas — revisar dataset"
    factura = con_lineas[0]
    assert all(isinstance(linea, LineaFactura) for linea in factura.lineas)
    assert all(linea.codigo_factura == factura.codigo for linea in factura.lineas)
    # Las líneas deben venir ordenadas por número de línea.
    nums = [linea.linea for linea in factura.lineas]
    assert nums == sorted(nums)


# ─── Filtros aplicados sobre la fuente real ────────────────────────────────


def test_filtro_fecha_entre_recorta_resultados(data_dev_dir):
    src = DbfSource(data_dev_dir)
    todas = src.get_facturas(Filtros())
    # Tomamos un rango estrecho centrado en una factura real para evitar
    # depender de los límites concretos del DATA_DEV.
    pivote = todas[0].fecha
    rango = Filtros(
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                (pivote.isoformat(), pivote.isoformat()),
            ),
        ],
    )
    resultado = src.get_facturas(rango)
    assert resultado, "El pivote debería incluirse a sí mismo"
    assert all(f.fecha == pivote for f in resultado)


def test_filtro_cliente_or(data_dev_dir):
    src = DbfSource(data_dev_dir)
    todas = src.get_facturas(Filtros())
    clientes_distintos = list({f.cliente_codigo for f in todas})[:2]
    if len(clientes_distintos) < 2:
        pytest.skip("DATA_DEV no tiene 2 clientes distintos en facturas")
    filtros = Filtros(
        operador=OperadorFiltro.OR,
        condiciones=[
            Condicion('cliente', OperadorCondicion.IGUAL, clientes_distintos[0]),
            Condicion('cliente', OperadorCondicion.IGUAL, clientes_distintos[1]),
        ],
    )
    resultado = src.get_facturas(filtros)
    assert resultado
    assert all(f.cliente_codigo in clientes_distintos for f in resultado)


def test_filtro_anidado_and_or_sobre_fuente_real(data_dev_dir):
    src = DbfSource(data_dev_dir)
    todas = src.get_facturas(Filtros())
    pivote = todas[0]
    filtros = Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                (pivote.fecha.isoformat(), pivote.fecha.isoformat()),
            ),
            Filtros(
                operador=OperadorFiltro.OR,
                condiciones=[
                    Condicion('cliente', OperadorCondicion.IGUAL, pivote.cliente_codigo),
                    Condicion('cliente', OperadorCondicion.IGUAL, '__inexistente__'),
                ],
            ),
        ],
    )
    resultado = src.get_facturas(filtros)
    assert any(f.codigo == pivote.codigo for f in resultado)


def test_rango_imposible_devuelve_lista_vacia(data_dev_dir):
    src = DbfSource(data_dev_dir)
    filtros = Filtros(
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                ('1900-01-01', '1900-01-02'),
            ),
        ],
    )
    assert src.get_facturas(filtros) == []


# ─── Garantía READ_ONLY ────────────────────────────────────────────────────


def test_apertura_es_read_only(data_dev_dir, monkeypatch):
    """Verifica explícitamente que `_open_table` abre en READ_ONLY.

    Se intercepta `dbf.Table.open` ANTES de construir el `DbfSource` para que
    el spy capture también la validación de esquema del constructor — no solo
    las consultas posteriores. Cualquier modo distinto de `dbf.READ_ONLY`
    debe hacer fallar este test: es la regla inviolable del proyecto
    (ver CLAUDE.md / Sección 12 del plan).
    """
    modos_observados: list[int] = []
    open_original = dbf_lib.Table.open

    def _spy_open(self, *args, mode=dbf_lib.READ_ONLY, **kwargs):
        modos_observados.append(mode)
        return open_original(self, *args, mode=mode, **kwargs)

    monkeypatch.setattr(dbf_lib.Table, 'open', _spy_open)

    src = DbfSource(data_dev_dir)  # → 4 aperturas durante _validate_schema
    src.get_clientes()
    src.get_articulos()
    src.get_facturas(Filtros())

    assert len(modos_observados) >= 4, (
        f"Se esperaban al menos 4 aperturas (validación de esquema), "
        f"observadas: {len(modos_observados)}"
    )
    assert all(m == dbf_lib.READ_ONLY for m in modos_observados), (
        f"Se abrió un DBF en modo distinto de READ_ONLY: {modos_observados}"
    )
