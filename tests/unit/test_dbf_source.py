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
    assert all(isinstance(f, Factura) for f in facturas)
    con_fecha = [f for f in facturas if f.fecha is not None]
    assert con_fecha, "DATA_DEV debe tener al menos una factura con FECHA"
    assert isinstance(con_fecha[0].fecha, date)
    assert isinstance(facturas[0].total_con_iva, Decimal)


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
    con_fecha = [f for f in todas if f.fecha is not None]
    assert con_fecha, "DATA_DEV no tiene ninguna factura con FECHA"
    pivote = con_fecha[0].fecha
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
    # Las facturas sin FECHA siempre pasan el filtro de fecha (aparecen en
    # preview como ROJO) — las ignoramos para verificar el recorte real.
    fechadas = [f for f in resultado if f.fecha is not None]
    assert fechadas, "El pivote debería incluirse a sí mismo"
    assert all(f.fecha == pivote for f in fechadas)


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
    con_fecha = [f for f in todas if f.fecha is not None]
    assert con_fecha, "DATA_DEV no tiene ninguna factura con FECHA"
    pivote = con_fecha[0]
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
    """Un rango sin fechadas tampoco arrastra a las sin-fecha: sin un rango
    de NUMERO con el que comparar, no hay hueco que rellenar y la preview
    queda vacía limpiamente."""
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


# ─── Robustez frente a registros corruptos / borrados ──────────────────────


def _crear_dbfs_minimos(tmp_path):
    """Crea un set mínimo de DBFs (cfactura, lfactura, clientes, material)
    con un único cliente, un único artículo y dos facturas válidas.

    Devuelve la ruta al directorio. El caller puede añadir registros
    extra (factura con FECHA vacía, registro borrado, etc.).
    """
    cfactura_specs = (
        'CODIGO C(10); SERIE C(4); NUMERO C(6); CLIENTE C(8); FECHA D;'
        ' TOTPTS N(12,2); TOTCONIVA N(12,2);'
        ' PTSBASE1 N(12,2); IVA1 N(5,2); RECEQUI1 N(5,2);'
        ' PTSBASE2 N(12,2); IVA2 N(5,2); RECEQUI2 N(5,2);'
        ' PTSBASE3 N(12,2); IVA3 N(5,2); RECEQUI3 N(5,2);'
        ' RETIRPF N(5,2); CONTABIL L'
    )
    lfactura_specs = (
        'CODIGO C(10); LINEA N(4,0); ARTICULO C(30); COMENTARIO C(80);'
        ' CANTIDAD N(10,2); PRECIOV N(10,2); IVA N(5,2); TOTLINEA N(12,2)'
    )
    clientes_specs = 'CODIGO C(8); NOMBRE C(40); NIF C(12)'
    material_specs = 'CLAVEMATE C(30); DESCRIPCIO C(50)'

    def _crea(nombre: str, specs: str):
        tabla = dbf_lib.Table(str(tmp_path / f'{nombre}.dbf'), specs, codepage='cp1252')
        tabla.open(mode=dbf_lib.READ_WRITE)
        return tabla

    cfactura = _crea('cfactura', cfactura_specs)
    cfactura.append({
        'CODIGO': 'F000000001', 'SERIE': '2026', 'NUMERO': '000001',
        'CLIENTE': 'CLI00001', 'FECHA': date(2026, 1, 10),
        'TOTPTS': Decimal('100'), 'TOTCONIVA': Decimal('121'),
        'PTSBASE1': Decimal('100'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
        'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
        'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
        'RETIRPF': Decimal('0'), 'CONTABIL': False,
    })
    cfactura.append({
        'CODIGO': 'F000000002', 'SERIE': '2026', 'NUMERO': '000002',
        'CLIENTE': 'CLI00001', 'FECHA': date(2026, 1, 11),
        'TOTPTS': Decimal('50'), 'TOTCONIVA': Decimal('60.5'),
        'PTSBASE1': Decimal('50'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
        'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
        'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
        'RETIRPF': Decimal('0'), 'CONTABIL': False,
    })

    lfactura = _crea('lfactura', lfactura_specs)
    for codigo in ('F000000001', 'F000000002'):
        lfactura.append({
            'CODIGO': codigo, 'LINEA': 1, 'ARTICULO': 'ART01', 'COMENTARIO': '',
            'CANTIDAD': Decimal('1'), 'PRECIOV': Decimal('50'),
            'IVA': Decimal('21'), 'TOTLINEA': Decimal('50'),
        })

    clientes = _crea('clientes', clientes_specs)
    clientes.append({'CODIGO': 'CLI00001', 'NOMBRE': 'Cliente Uno', 'NIF': '00000001A'})

    material = _crea('material', material_specs)
    material.append({'CLAVEMATE': 'ART01', 'DESCRIPCIO': 'Artículo de prueba'})

    return tmp_path, cfactura, lfactura, clientes, material


def test_factura_con_fecha_vacia_aparece_con_fecha_none(tmp_path, caplog):
    """Una cabecera con FECHA=None se incluye en la preview con `fecha=None`
    para que aparezca como ROJO y el contable pueda corregirla. Antes se
    omitía silenciosamente y creaba huecos en la secuencia de números
    (bug real: factura 2026/000195 en producción).

    Añadimos también una fechada con NUMERO 000300 para que el rango cubra
    la sin-fecha — sin un hueco real que rellenar, la nueva lógica de
    `get_facturas` la descarta a propósito."""
    import logging

    ruta, cfactura, lfactura, clientes, material = _crear_dbfs_minimos(tmp_path)
    try:
        cfactura.append({
            'CODIGO': '2026000195', 'SERIE': '2026', 'NUMERO': '000195',
            'CLIENTE': 'CLI00001', 'FECHA': None,
            'TOTPTS': Decimal('80.6'), 'TOTCONIVA': Decimal('97.53'),
            'PTSBASE1': Decimal('80.6'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
            'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
            'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
            'RETIRPF': Decimal('0'), 'CONTABIL': True,
        })
        cfactura.append({
            'CODIGO': 'F000000300', 'SERIE': '2026', 'NUMERO': '000300',
            'CLIENTE': 'CLI00001', 'FECHA': date(2026, 1, 20),
            'TOTPTS': Decimal('50'), 'TOTCONIVA': Decimal('60.5'),
            'PTSBASE1': Decimal('50'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
            'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
            'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
            'RETIRPF': Decimal('0'), 'CONTABIL': False,
        })
    finally:
        cfactura.close()
        lfactura.close()
        clientes.close()
        material.close()

    src = DbfSource(ruta)
    with caplog.at_level(logging.WARNING, logger='app.sources.dbf_source'):
        facturas = src.get_facturas(Filtros())

    por_codigo = {f.codigo.strip(): f for f in facturas}
    assert '2026000195' in por_codigo, "La factura sin FECHA debe aparecer en la preview"
    incompleta = por_codigo['2026000195']
    assert incompleta.fecha is None
    assert incompleta.total_con_iva == Decimal('97.53')
    assert any('2026000195' in r.getMessage() for r in caplog.records)


def _crear_sin_fecha(tabla, codigo: str, numero: str, serie: str = '2026') -> None:
    tabla.append({
        'CODIGO': codigo, 'SERIE': serie, 'NUMERO': numero,
        'CLIENTE': 'CLI00001', 'FECHA': None,
        'TOTPTS': Decimal('10'), 'TOTCONIVA': Decimal('12.10'),
        'PTSBASE1': Decimal('10'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
        'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
        'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
        'RETIRPF': Decimal('0'), 'CONTABIL': False,
    })


def test_factura_sin_fecha_aparece_si_numero_dentro_del_rango(tmp_path):
    """Cuando la preview cubre del 000001 al 000002, una factura sin FECHA
    con NUMERO 000002 (extremo) o 000001 (extremo) debe aparecer para que
    el contable pueda corregirla — es exactamente el hueco que se quiere
    rellenar."""
    ruta, cfactura, lfactura, clientes, material = _crear_dbfs_minimos(tmp_path)
    try:
        _crear_sin_fecha(cfactura, 'SINFECHA01', '000002')
    finally:
        cfactura.close()
        lfactura.close()
        clientes.close()
        material.close()

    src = DbfSource(ruta)
    filtro_enero = Filtros(
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                ('2026-01-01', '2026-01-31'),
            ),
        ],
    )
    codigos = {f.codigo.strip() for f in src.get_facturas(filtro_enero)}
    assert 'SINFECHA01' in codigos


def test_factura_sin_fecha_se_excluye_si_numero_fuera_del_rango(tmp_path):
    """Una factura sin FECHA con NUMERO muy lejano (p.ej. 000500 cuando la
    preview cubre 000001-000002) NO debe aparecer — corresponde a otro mes
    y mostrarla contaminaría la preview sin rellenar ningún hueco real."""
    ruta, cfactura, lfactura, clientes, material = _crear_dbfs_minimos(tmp_path)
    try:
        _crear_sin_fecha(cfactura, 'SINFECHA01', '000500')
    finally:
        cfactura.close()
        lfactura.close()
        clientes.close()
        material.close()

    src = DbfSource(ruta)
    filtro_enero = Filtros(
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                ('2026-01-01', '2026-01-31'),
            ),
        ],
    )
    codigos = {f.codigo.strip() for f in src.get_facturas(filtro_enero)}
    assert 'SINFECHA01' not in codigos


def test_factura_sin_fecha_no_aparece_si_no_hay_fechadas(tmp_path):
    """Si el filtro no devuelve ninguna factura con FECHA, no hay rango con
    el que comparar — las sin-fecha quedan fuera para no contaminar una
    preview vacía con cabeceras que el contable no estaba buscando."""
    ruta, cfactura, lfactura, clientes, material = _crear_dbfs_minimos(tmp_path)
    try:
        _crear_sin_fecha(cfactura, 'SINFECHA01', '000001')
    finally:
        cfactura.close()
        lfactura.close()
        clientes.close()
        material.close()

    src = DbfSource(ruta)
    filtro_lejano = Filtros(
        condiciones=[
            Condicion(
                'fecha',
                OperadorCondicion.ENTRE,
                ('1900-01-01', '1900-01-02'),
            ),
        ],
    )
    codigos = {f.codigo.strip() for f in src.get_facturas(filtro_lejano)}
    assert codigos == set()


def test_registros_borrados_se_ignoran(tmp_path):
    """Los registros marcados como borrados (`*` de FoxPro, sin PACK) no
    deben aparecer en el preview ni en ninguna lista — son fantasmas que
    GESDAI mantiene en el fichero hasta el próximo PACK."""
    ruta, cfactura, lfactura, clientes, material = _crear_dbfs_minimos(tmp_path)
    try:
        clientes.append({'CODIGO': 'CLI99998', 'NOMBRE': 'Borrado', 'NIF': ''})
        material.append({'CLAVEMATE': 'ARTBORR', 'DESCRIPCIO': 'Artículo borrado'})
        cfactura.append({
            'CODIGO': 'FBORRADA01', 'SERIE': '2026', 'NUMERO': '000099',
            'CLIENTE': 'CLI00001', 'FECHA': date(2026, 1, 5),
            'TOTPTS': Decimal('10'), 'TOTCONIVA': Decimal('12.1'),
            'PTSBASE1': Decimal('10'), 'IVA1': Decimal('21'), 'RECEQUI1': Decimal('0'),
            'PTSBASE2': Decimal('0'), 'IVA2': Decimal('0'), 'RECEQUI2': Decimal('0'),
            'PTSBASE3': Decimal('0'), 'IVA3': Decimal('0'), 'RECEQUI3': Decimal('0'),
            'RETIRPF': Decimal('0'), 'CONTABIL': False,
        })
        # Marcar como borrados los últimos registros añadidos.
        for tabla in (cfactura, clientes, material):
            dbf_lib.delete(tabla[-1])
    finally:
        cfactura.close()
        lfactura.close()
        clientes.close()
        material.close()

    src = DbfSource(ruta)
    codigos_factura = {f.codigo.strip() for f in src.get_facturas(Filtros())}
    assert 'FBORRADA01' not in codigos_factura

    codigos_cliente = {c.codigo.strip() for c in src.get_clientes()}
    assert 'CLI99998' not in codigos_cliente

    claves_articulo = {a.clave.strip() for a in src.get_articulos()}
    assert 'ARTBORR' not in claves_articulo

    with pytest.raises(KeyError):
        src.get_cliente('CLI99998')
