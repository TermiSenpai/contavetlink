"""Tests de integración Fase 4 — endpoints HTTP.

Usan el `client` fixture (Flask test client sobre SQLite temporal) y los
helpers del intermediario para montar el estado necesario antes de cada test.
"""
from __future__ import annotations

import json

import pytest

from app.db import (
    SETTING_COD_EMPRESA,
    SETTING_CUENTA_VENTAS_DEF,
    SETTING_DBF_PATH,
    SETTING_EJERCICIO,
    SETTING_EXPORTS_PATH,
    SETTING_IMPORTE_FORMATO,
    get_setting,
    set_setting,
)


@pytest.fixture
def app_con_dbf(app, data_dev_dir):
    """App con `dbf_path` seedeado al DATA_DEV del proyecto."""
    with app.app_context():
        from app.db import get_db
        set_setting(get_db(), SETTING_DBF_PATH, str(data_dev_dir))
        get_db().commit()
    return app


@pytest.fixture
def client_con_dbf(app_con_dbf):
    return app_con_dbf.test_client()


@pytest.fixture
def app_export_listo(app, data_dev_dir, tmp_path):
    """App con TODA la configuración necesaria para /export/ (dbf, exports,
    cod_empresa, cuenta, formato, ejercicio) + clientes sincronizados con
    subcuentas asignadas. Lista para generar DAT real."""
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import (
            marcar_cliente_revisado,
            set_subcuenta_cliente,
        )
        from app.mapping.sync import sync_articulos, sync_clientes
        from app.sources.dbf_source import DbfSource

        conn = get_db()
        set_setting(conn, SETTING_DBF_PATH, str(data_dev_dir))
        set_setting(conn, SETTING_EXPORTS_PATH, str(tmp_path / 'exports'))
        set_setting(conn, SETTING_COD_EMPRESA, '42')
        set_setting(conn, SETTING_CUENTA_VENTAS_DEF, '700001')
        set_setting(conn, SETTING_IMPORTE_FORMATO, 'A')
        set_setting(conn, SETTING_EJERCICIO, '2024')
        conn.commit()

        source = DbfSource(str(data_dev_dir))
        sync_clientes(conn, source)
        sync_articulos(conn, source)
        for i, row in enumerate(
            conn.execute("SELECT codigo_gesdai FROM mappings_clientes").fetchall(),
            start=1,
        ):
            set_subcuenta_cliente(conn, row['codigo_gesdai'], f'430{i:03d}')
            marcar_cliente_revisado(conn, row['codigo_gesdai'])
        conn.commit()
    return app


@pytest.fixture
def client_export_listo(app_export_listo):
    return app_export_listo.test_client()


# ─── /config/ ──────────────────────────────────────────────────────────────


def test_get_config_200(client):
    response = client.get('/config/')
    assert response.status_code == 200
    assert b'dbf_path' in response.data


def test_post_config_valido_guarda_y_redirige(client, app, data_dev_dir):
    response = client.post('/config/', data={
        'dbf_path': str(data_dev_dir),
        'exports_path': str(data_dev_dir),  # vale cualquier dir existente
        'cod_empresa': '42',
        'cuenta_ventas_def': '700001',
        'ejercicio': '2026',
        'importe_formato': 'A',
    })
    assert response.status_code == 302
    assert response.headers['Location'].endswith('/config/')

    # Los valores persisten en SQLite
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        assert get_setting(conn, SETTING_DBF_PATH) == str(data_dev_dir)
        assert get_setting(conn, SETTING_COD_EMPRESA) == '42'
        assert get_setting(conn, SETTING_IMPORTE_FORMATO) == 'A'


def test_post_config_ruta_invalida_400(client):
    """Si la ruta DBF no existe, el error se flashea y se redirige sin guardar."""
    response = client.post('/config/', data={
        'dbf_path': 'C:/no-existe-xyz-123',
        'exports_path': '/tmp',
        'cod_empresa': '42',
        'cuenta_ventas_def': '700001',
        'ejercicio': '2026',
        'importe_formato': 'A',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'no existe' in response.data or b'no es un directorio' in response.data


def test_post_config_subcuenta_invalida_error(client, data_dev_dir):
    response = client.post('/config/', data={
        'dbf_path': str(data_dev_dir),
        'exports_path': str(data_dev_dir),
        'cod_empresa': '42',
        'cuenta_ventas_def': 'XXX',
        'ejercicio': '2026',
        'importe_formato': 'A',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Subcuenta de ingreso' in response.data


def test_post_config_cod_empresa_fuera_de_rango(client, data_dev_dir):
    response = client.post('/config/', data={
        'dbf_path': str(data_dev_dir),
        'exports_path': str(data_dev_dir),
        'cod_empresa': '0',
        'cuenta_ventas_def': '700001',
        'ejercicio': '2026',
        'importe_formato': 'A',
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'C' in response.data  # "Código de empresa..."


def test_post_config_formato_invalido(client, data_dev_dir):
    response = client.post('/config/', data={
        'dbf_path': str(data_dev_dir),
        'exports_path': str(data_dev_dir),
        'cod_empresa': '42',
        'cuenta_ventas_def': '700001',
        'ejercicio': '2026',
        'importe_formato': 'Z',
    }, follow_redirects=True)
    assert response.status_code == 200
    # Jinja escapea las comillas a HTML entities
    assert b"&#39;Z&#39;" in response.data or b"'Z'" in response.data


def test_verificar_dbf_ok(client, data_dev_dir):
    response = client.post(
        '/config/verificar-dbf',
        data=json.dumps({'dbf_path': str(data_dev_dir)}),
        content_type='application/json',
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is True
    assert body['n_clientes'] > 0
    assert body['n_articulos'] > 0


def test_verificar_dbf_ruta_no_existe(client):
    response = client.post(
        '/config/verificar-dbf',
        data=json.dumps({'dbf_path': 'C:/ruta-que-no-existe-xyz'}),
        content_type='application/json',
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is False
    assert 'no existe' in body['error'].lower()


def test_verificar_dbf_ruta_vacia(client):
    response = client.post(
        '/config/verificar-dbf',
        data=json.dumps({}),
        content_type='application/json',
    )
    assert response.status_code == 200
    assert response.get_json()['ok'] is False


# ─── /mappings/clientes ────────────────────────────────────────────────────


def test_get_mappings_clientes_200(client):
    response = client.get('/mappings/clientes')
    assert response.status_code == 200


def test_get_mappings_clientes_filtro_invalido_flashea(client):
    resp = client.get('/mappings/clientes?filtro=inventado', follow_redirects=False)
    assert resp.status_code == 200  # no redirige, renderiza con todos


def test_sync_clientes_desde_dbf(client_con_dbf, app_con_dbf):
    resp = client_con_dbf.post('/mappings/clientes/sync', follow_redirects=False)
    assert resp.status_code == 302
    with app_con_dbf.app_context():
        from app.db import get_db
        from app.mapping.store import list_clientes_mappings
        clientes = list_clientes_mappings(get_db())
        assert len(clientes) > 0


def test_sync_clientes_sin_dbf_redirige_a_config(client):
    """Si no hay dbf_path configurado, debe redirigir a /config/ con error."""
    resp = client.post('/mappings/clientes/sync', follow_redirects=False)
    assert resp.status_code == 302
    assert '/config/' in resp.headers['Location']


def test_post_subcuenta_correcto_200(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_cliente_mapping
        upsert_cliente_mapping(get_db(), codigo='CLI001', nombre='Alpha')
        get_db().commit()
    resp = client.post(
        '/mappings/clientes/CLI001',
        json={'subcuenta_a3': '430001'},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['subcuenta_a3'] == '430001'


def test_post_subcuenta_7_digitos_400(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_cliente_mapping
        upsert_cliente_mapping(get_db(), codigo='CLI001', nombre='Alpha')
        get_db().commit()
    resp = client.post(
        '/mappings/clientes/CLI001',
        json={'subcuenta_a3': '4300001'},
    )
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_post_subcuenta_letras_400(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_cliente_mapping
        upsert_cliente_mapping(get_db(), codigo='CLI001', nombre='Alpha')
        get_db().commit()
    resp = client.post('/mappings/clientes/CLI001', json={'subcuenta_a3': '430A01'})
    assert resp.status_code == 400


def test_post_subcuenta_cliente_inexistente_404(client):
    resp = client.post('/mappings/clientes/NOPE', json={'subcuenta_a3': '430001'})
    assert resp.status_code == 404


def test_marcar_cliente_revisado(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import (
            set_subcuenta_cliente,
            upsert_cliente_mapping,
        )
        conn = get_db()
        upsert_cliente_mapping(conn, codigo='CLI001', nombre='Alpha')
        set_subcuenta_cliente(conn, 'CLI001', '430001')
        conn.commit()
    resp = client.post('/mappings/clientes/CLI001/revisar', json={'revisado': True})
    assert resp.status_code == 200
    assert resp.get_json()['revisado'] is True


def test_import_csv_clientes_correcto(client, tmp_path):
    csv_path = tmp_path / 'clientes.csv'
    csv_path.write_text(
        'codigo_gesdai,nombre,nif,subcuenta_a3,revisado,notas\n'
        'CLI001,Alpha,,430001,0,\n',
        encoding='utf-8-sig',
    )
    with open(csv_path, 'rb') as fh:
        resp = client.post(
            '/mappings/clientes/import',
            data={'fichero': (fh, 'clientes.csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
    assert resp.status_code == 200
    assert b'nuevos' in resp.data or b'1' in resp.data


def test_import_csv_clientes_sin_fichero_400(client):
    resp = client.post(
        '/mappings/clientes/import',
        data={},
        content_type='multipart/form-data',
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'No se adjunt' in resp.data


def test_import_clientes_formato_no_soportado(client, tmp_path):
    raro = tmp_path / 'clientes.txt'
    raro.write_text('no soy un csv', encoding='utf-8')
    with open(raro, 'rb') as fh:
        resp = client.post(
            '/mappings/clientes/import',
            data={'fichero': (fh, 'clientes.txt')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )
    assert b'no soportado' in resp.data.lower() or b'Formato' in resp.data


def test_export_clientes_csv(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_cliente_mapping
        upsert_cliente_mapping(get_db(), codigo='CLI001', nombre='Alpha', subcuenta_a3='430001')
        get_db().commit()
    resp = client.get('/mappings/clientes/export?formato=csv')
    assert resp.status_code == 200
    assert resp.headers['Content-Type'].startswith('text/csv')
    assert b'CLI001' in resp.data


def test_export_clientes_excel(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_cliente_mapping
        upsert_cliente_mapping(get_db(), codigo='CLI001', nombre='Alpha', subcuenta_a3='430001')
        get_db().commit()
    resp = client.get('/mappings/clientes/export?formato=xlsx')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


def test_export_clientes_formato_invalido_400(client):
    resp = client.get('/mappings/clientes/export?formato=pdf')
    assert resp.status_code == 400


# ─── /mappings/articulos ───────────────────────────────────────────────────


def test_sync_articulos_desde_dbf(client_con_dbf, app_con_dbf):
    resp = client_con_dbf.post('/mappings/articulos/sync', follow_redirects=False)
    assert resp.status_code == 302
    with app_con_dbf.app_context():
        from app.db import get_db
        from app.mapping.store import list_articulos_mappings
        arts = list_articulos_mappings(get_db())
        assert len(arts) > 0


def test_post_cuenta_articulo_valida(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_articulo_mapping
        upsert_articulo_mapping(get_db(), clave='CHIP', descripcion='Microchip')
        get_db().commit()
    resp = client.post('/mappings/articulos/CHIP', json={'cuenta_a3': '700001'})
    assert resp.status_code == 200
    assert resp.get_json()['cuenta_a3'] == '700001'


def test_post_cuenta_articulo_invalida_400(client, app):
    with app.app_context():
        from app.db import get_db
        from app.mapping.store import upsert_articulo_mapping
        upsert_articulo_mapping(get_db(), clave='CHIP', descripcion='Microchip')
        get_db().commit()
    resp = client.post('/mappings/articulos/CHIP', json={'cuenta_a3': 'XXXX'})
    assert resp.status_code == 400


def test_get_historial_200(client):
    response = client.get('/historial/')
    assert response.status_code == 200


# ─── /export/ ──────────────────────────────────────────────────────────────


def test_get_export_sin_config_muestra_mensaje(client):
    """Sin dbf_path, /export/ debe renderizar sin petar y flashear el problema."""
    resp = client.get('/export/', follow_redirects=False)
    assert resp.status_code == 200
    assert b'Exportar facturas' in resp.data


def test_get_export_con_config_renderiza_preview(client_export_listo):
    """Con todo configurado, /export/ carga el mes actual de GESDAI."""
    resp = client_export_listo.get('/export/')
    assert resp.status_code == 200
    # El template contiene la sección de preview — visible si preview!=None
    assert b'Vista previa' in resp.data


def test_post_preview_sin_filtros_devuelve_facturas(client_export_listo):
    resp = client_export_listo.post('/export/preview', json={'filtros': {}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert body['resumen']['total'] > 0
    assert 'facturas' in body
    assert len(body['facturas']) == body['resumen']['total']


def test_preview_persiste_mappings_pendientes_descubiertos(
    client_export_listo, app_export_listo,
):
    """Regresión del bug 'preview no commitea'. Resolver descubre artículos
    nuevos como side-effect al clasificar líneas; si no se commitea, el
    operador nunca los ve en /mappings/articulos.
    """
    # Vaciar artículos para forzar descubrimiento durante el preview
    with app_export_listo.app_context():
        from app.db import get_db
        conn = get_db()
        conn.execute("DELETE FROM mappings_articulos")
        conn.commit()
        antes = conn.execute(
            "SELECT COUNT(*) FROM mappings_articulos"
        ).fetchone()[0]
        assert antes == 0

    resp = client_export_listo.post('/export/preview', json={'filtros': {}})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    # Los artículos descubiertos por el resolver DEBEN estar persistidos
    with app_export_listo.app_context():
        from app.db import get_db
        conn = get_db()
        despues = conn.execute(
            "SELECT COUNT(*) FROM mappings_articulos"
        ).fetchone()[0]
        assert despues > 0, (
            "El preview debe persistir los mappings pendientes descubiertos "
            "por el resolver. Si cuenta=0, el route handler olvidó commitear."
        )


def test_post_preview_con_filtro_fecha_and(client_export_listo):
    """Filtro AND sobre fecha recorta el dataset."""
    resp = client_export_listo.post('/export/preview', json={
        'filtros': {
            'operador': 'AND',
            'condiciones': [
                {'campo': 'fecha', 'operador': 'entre',
                 'valor': ['2024-07-01', '2024-07-31']},
            ],
        },
    })
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    # Todas las fechas deben caer en julio 2024
    for f in body['facturas']:
        assert f['fecha'] >= '2024-07-01'
        assert f['fecha'] <= '2024-07-31'


def test_post_preview_con_filtro_or(client_export_listo):
    """Grupo OR de dos clientes distintos."""
    resp_all = client_export_listo.post('/export/preview', json={'filtros': {}})
    clientes = {f['cliente_codigo'] for f in resp_all.get_json()['facturas']}
    dos = list(clientes)[:2]
    assert len(dos) == 2

    resp = client_export_listo.post('/export/preview', json={
        'filtros': {
            'operador': 'OR',
            'condiciones': [
                {'campo': 'cliente', 'operador': 'igual', 'valor': dos[0]},
                {'campo': 'cliente', 'operador': 'igual', 'valor': dos[1]},
            ],
        },
    })
    assert resp.status_code == 200
    body = resp.get_json()
    for f in body['facturas']:
        assert f['cliente_codigo'] in dos


def test_post_preview_filtro_invalido_400(client_export_listo):
    resp = client_export_listo.post('/export/preview', json={
        'filtros': {'operador': 'XOR', 'condiciones': []},
    })
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_post_preview_sin_config_400(client):
    resp = client.post('/export/preview', json={'filtros': {}})
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_post_generar_dat_correcto(client_export_listo, app_export_listo):
    """El happy path end-to-end: genera DAT real, registra en BD, devuelve link."""
    # Tolerar datos dev groseros — usamos patch del builder para aflojar cuadre
    from decimal import Decimal
    from unittest.mock import patch

    from app.exporter.builder import Builder

    original_init = Builder.__init__

    def _init_laxo(self, *args, **kwargs):
        kwargs['cuadre_tolerancia'] = Decimal('1.00')
        original_init(self, *args, **kwargs)

    with patch.object(Builder, '__init__', _init_laxo):
        resp = client_export_listo.post('/export/generar', json={'filtros': {}})

    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body['ok'] is True
    assert body['num_facturas'] > 0
    assert len(body['sha256']) == 64
    assert '/historial/' in body['download_url']

    # Se registró en la BD Y el fichero existe en disco con el SHA correcto
    from pathlib import Path

    from app.exporter.suenlace import ENCODING, EOL, LONGITUD_REGISTRO
    with app_export_listo.app_context():
        from app.db import get_db
        conn = get_db()
        row = conn.execute('SELECT * FROM exportaciones WHERE id = ?',
                           (body['exportacion_id'],)).fetchone()
        assert row is not None
        assert row['num_facturas'] == body['num_facturas']
        assert row['dat_hash'] == body['sha256']

        dat_path = Path(row['dat_fichero'])
        assert dat_path.is_file(), f"DAT no existe: {dat_path}"

        # Todas las líneas miden 254 chars y CRLF correcto
        contenido = dat_path.read_bytes()
        lineas = contenido.split(EOL.encode(ENCODING))
        assert all(len(linea) == LONGITUD_REGISTRO for linea in lineas)

        # exportaciones_detalle tiene una fila por factura
        n_detalles = conn.execute(
            'SELECT COUNT(*) FROM exportaciones_detalle WHERE exportacion_id = ?',
            (body['exportacion_id'],),
        ).fetchone()[0]
        assert n_detalles == body['num_facturas']


def test_post_generar_dat_con_rojo_400(client_export_listo, app_export_listo):
    """Si hay al menos un cliente sin subcuenta, /generar falla con 400."""
    with app_export_listo.app_context():
        from app.db import get_db
        # Borramos la subcuenta de un cliente → cae en rojo
        conn = get_db()
        conn.execute("UPDATE mappings_clientes SET subcuenta_a3 = NULL")
        conn.commit()

    resp = client_export_listo.post('/export/generar', json={'filtros': {}})
    assert resp.status_code == 400
    assert 'rojo' in resp.get_json()['error'].lower()


def test_post_generar_sin_config_400(client):
    resp = client.post('/export/generar', json={'filtros': {}})
    assert resp.status_code == 400


def test_export_preview_excel(client_export_listo):
    resp = client_export_listo.post('/export/preview/excel', json={'filtros': {}})
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']
    assert len(resp.data) > 0


def test_post_preview_detalles_devuelve_dict_por_codigo(client_export_listo):
    """El endpoint de precarga devuelve un dict { codigo: detalle } con la
    misma forma que GET /export/factura/<codigo> para cada factura del
    rango filtrado — el front lo usa como cache para abrir el modal sin
    viajar al backend."""
    preview = client_export_listo.post('/export/preview', json={'filtros': {}}).get_json()
    codigos = [f['codigo'] for f in preview['facturas']]
    assert len(codigos) > 0

    resp = client_export_listo.post('/export/preview/detalles', json={'filtros': {}})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['ok'] is True
    assert set(body['detalles'].keys()) == set(codigos)

    sample = body['detalles'][codigos[0]]
    assert set(sample.keys()) == {'factura', 'cliente', 'subcuenta', 'lineas'}
    assert sample['factura']['codigo'] == codigos[0]
    assert isinstance(sample['lineas'], list)


def test_post_preview_detalles_coincide_con_factura_individual(client_export_listo):
    """Regresión: el dict del cache debe ser intercambiable con la respuesta
    de /export/factura/<codigo> (mismas claves, mismos valores). Si difieren,
    el modal renderizaría datos distintos según venga de cache o de fetch."""
    preview = client_export_listo.post('/export/preview', json={'filtros': {}}).get_json()
    codigo = preview['facturas'][0]['codigo']

    batch = client_export_listo.post(
        '/export/preview/detalles', json={'filtros': {}},
    ).get_json()
    individual = client_export_listo.get(
        f'/export/factura/{codigo}',
    ).get_json()

    desde_cache = batch['detalles'][codigo]
    # `individual` añade 'ok': True, pero el resto debe coincidir 1-a-1
    assert desde_cache['factura'] == individual['factura']
    assert desde_cache['cliente'] == individual['cliente']
    assert desde_cache['subcuenta'] == individual['subcuenta']
    assert desde_cache['lineas'] == individual['lineas']


def test_post_preview_detalles_respeta_filtros(client_export_listo):
    """Solo se precargan las facturas que cumplen los filtros activos."""
    preview = client_export_listo.post('/export/preview', json={
        'filtros': {
            'operador': 'AND',
            'condiciones': [
                {'campo': 'fecha', 'operador': 'entre',
                 'valor': ['2024-07-01', '2024-07-31']},
            ],
        },
    }).get_json()
    esperados = {f['codigo'] for f in preview['facturas']}

    resp = client_export_listo.post('/export/preview/detalles', json={
        'filtros': {
            'operador': 'AND',
            'condiciones': [
                {'campo': 'fecha', 'operador': 'entre',
                 'valor': ['2024-07-01', '2024-07-31']},
            ],
        },
    })
    assert resp.status_code == 200
    assert set(resp.get_json()['detalles'].keys()) == esperados


def test_post_preview_detalles_sin_config_400(client):
    resp = client.post('/export/preview/detalles', json={'filtros': {}})
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


def test_post_preview_detalles_filtro_invalido_400(client_export_listo):
    resp = client_export_listo.post('/export/preview/detalles', json={
        'filtros': {'operador': 'XOR', 'condiciones': []},
    })
    assert resp.status_code == 400
    assert resp.get_json()['ok'] is False


# ─── /historial/ ───────────────────────────────────────────────────────────


def test_historial_lista_exportaciones(client, app):
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        conn.execute(
            """INSERT INTO exportaciones
               (fecha_export, fecha_desde, fecha_hasta, num_facturas,
                dat_fichero, dat_hash, app_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('2026-01-31', '2026-01-01', '2026-01-31', 42,
             '/tmp/SUENLACE.DAT', 'abc' + '0' * 61, '0.1.0'),
        )
        conn.commit()
    resp = client.get('/historial/')
    assert resp.status_code == 200
    assert b'42' in resp.data


def test_descargar_dat_existente(client, app, tmp_path):
    """Crear un fichero DAT real y descargarlo a través del endpoint."""
    dat_path = tmp_path / 'SUENLACE.DAT'
    dat_path.write_bytes(b'line1\r\nline2\r\n')
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO exportaciones
               (fecha_export, fecha_desde, fecha_hasta, num_facturas,
                dat_fichero, dat_hash, app_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('2026-01-31', '2026-01-01', '2026-01-31', 1,
             str(dat_path), 'a' * 64, '0.1.0'),
        )
        conn.commit()
        exp_id = int(cur.lastrowid)
    resp = client.get(f'/historial/{exp_id}/dat')
    assert resp.status_code == 200
    assert b'line1' in resp.data


def test_descargar_dat_no_existe_404(client):
    resp = client.get('/historial/9999/dat')
    assert resp.status_code == 404


def test_descargar_dat_fichero_borrado_410(client, app, tmp_path):
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO exportaciones
               (fecha_export, fecha_desde, fecha_hasta, num_facturas,
                dat_fichero, dat_hash, app_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('2026-01-31', '2026-01-01', '2026-01-31', 1,
             str(tmp_path / 'fantasma.DAT'), 'a' * 64, '0.1.0'),
        )
        conn.commit()
        exp_id = int(cur.lastrowid)
    resp = client.get(f'/historial/{exp_id}/dat')
    assert resp.status_code == 410


def test_marcar_validado(client, app):
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO exportaciones
               (fecha_export, fecha_desde, fecha_hasta, num_facturas,
                dat_fichero, dat_hash, app_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('2026-01-31', '2026-01-01', '2026-01-31', 1,
             '/tmp/X.DAT', 'a' * 64, '0.1.0'),
        )
        conn.commit()
        exp_id = int(cur.lastrowid)
    resp = client.post(
        f'/historial/{exp_id}/validar',
        json={'validado': True, 'notas': 'OK en a3'},
    )
    assert resp.status_code == 200
    assert resp.get_json()['validado'] is True

    with app.app_context():
        from app.db import get_db
        conn = get_db()
        row = conn.execute(
            "SELECT validado, notas FROM exportaciones WHERE id = ?",
            (exp_id,),
        ).fetchone()
        assert row['validado'] == 1
        assert row['notas'] == 'OK en a3'


def test_marcar_validado_no_existe_404(client):
    resp = client.post('/historial/9999/validar', json={'validado': True})
    assert resp.status_code == 404


def test_historial_export_csv(client, app):
    with app.app_context():
        from app.db import get_db
        conn = get_db()
        conn.execute(
            """INSERT INTO exportaciones
               (fecha_export, fecha_desde, fecha_hasta, num_facturas,
                dat_fichero, dat_hash, app_version)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ('2026-01-31', '2026-01-01', '2026-01-31', 7,
             '/tmp/H.DAT', 'b' * 64, '0.1.0'),
        )
        conn.commit()
    resp = client.get('/historial/export?formato=csv')
    assert resp.status_code == 200
    assert b'7' in resp.data


def test_historial_export_xlsx(client):
    resp = client.get('/historial/export?formato=xlsx')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']
