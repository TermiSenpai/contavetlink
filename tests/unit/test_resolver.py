"""Tests Fase 3 — pipeline de resolución mapping → keyword → default."""
from __future__ import annotations

import pytest

from app.mapping.keywords import add_keyword
from app.mapping.resolver import (
    ClienteSinSubcuentaError,
    Resolver,
    TipoResolucion,
)
from app.mapping.store import (
    SubcuentaInvalidaError,
    get_articulo_mapping,
    marcar_articulo_revisado,
    marcar_cliente_revisado,
    set_cuenta_articulo,
    set_subcuenta_cliente,
    upsert_articulo_mapping,
    upsert_cliente_mapping,
)

CUENTA_DEFAULT = '700001'


# ─── Resolución de artículos ──────────────────────────────────────────────


def test_resolucion_mapping_sobre_keyword(db_conn):
    """Si existe mapping revisado, gana siempre sobre keyword."""
    upsert_articulo_mapping(db_conn, clave='CHIP', descripcion='Microchip')
    set_cuenta_articulo(db_conn, 'CHIP', '700100')
    marcar_articulo_revisado(db_conn, 'CHIP')
    add_keyword(db_conn, keyword='CHIP', cuenta_a3='700200', prioridad=50)

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_articulo('CHIP')

    assert resultado.tipo == TipoResolucion.MAPPING
    assert resultado.cuenta_a3 == '700100'


def test_resolucion_keyword_cuando_no_hay_mapping(db_conn):
    add_keyword(db_conn, keyword='cert', cuenta_a3='755001', prioridad=50)
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)

    resultado = resolver.resolver_articulo('CERT-SALUD')

    assert resultado.tipo == TipoResolucion.KEYWORD
    assert resultado.cuenta_a3 == '755001'


def test_resolucion_keyword_prioridad_gana(db_conn):
    add_keyword(db_conn, keyword='cert', cuenta_a3='755001', prioridad=10)
    add_keyword(db_conn, keyword='salud', cuenta_a3='700200', prioridad=80)
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)

    resultado = resolver.resolver_articulo('CERT DE SALUD')

    assert resultado.cuenta_a3 == '700200'


def test_resolucion_default_sin_keyword(db_conn):
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_articulo('ARTICULO-NUEVO')

    assert resultado.tipo == TipoResolucion.DEFAULT
    assert resultado.cuenta_a3 == CUENTA_DEFAULT


def test_resolucion_keyword_persiste_pendiente(db_conn):
    """Cuando entra por keyword, debe quedar en mappings_articulos como pendiente."""
    add_keyword(db_conn, keyword='cert', cuenta_a3='755001')
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)

    resolver.resolver_articulo('CERT-SALUD')

    fila = get_articulo_mapping(db_conn, 'CERT-SALUD')
    assert fila is not None
    assert fila['cuenta_a3'] == '755001'
    assert fila['revisado'] == 0, "debe quedar pendiente, no revisado"


def test_texto_libre_se_guarda_pendiente(db_conn):
    """Un texto sin keyword match debe persistirse con la cuenta default
    y marcado pendiente, para que aparezca en la UI."""
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resolver.resolver_articulo('DESCRIPCIÓN RARA SIN KEYWORD')

    fila = get_articulo_mapping(db_conn, 'DESCRIPCIÓN RARA SIN KEYWORD')
    assert fila is not None
    assert fila['cuenta_a3'] == CUENTA_DEFAULT
    assert fila['revisado'] == 0


def test_resolver_no_pisa_mapping_revisado_con_keyword(db_conn):
    """Una fila revisada NO debe ser sobreescrita por una nueva resolución."""
    upsert_articulo_mapping(db_conn, clave='CHIP', descripcion='Microchip')
    set_cuenta_articulo(db_conn, 'CHIP', '700100')
    marcar_articulo_revisado(db_conn, 'CHIP')
    add_keyword(db_conn, keyword='CHIP', cuenta_a3='755999')

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resolver.resolver_articulo('CHIP')

    fila = get_articulo_mapping(db_conn, 'CHIP')
    assert fila['cuenta_a3'] == '700100', "no se debe tocar un revisado"
    assert fila['revisado'] == 1


def test_resolver_clave_vacia_devuelve_default_sin_persistir(db_conn):
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_articulo('')

    assert resultado.tipo == TipoResolucion.DEFAULT
    assert resultado.cuenta_a3 == CUENTA_DEFAULT
    # Sin clave, no persistimos nada (no tendría sentido)
    assert get_articulo_mapping(db_conn, '') is None


def test_resolver_cuenta_default_se_valida(db_conn):
    with pytest.raises(SubcuentaInvalidaError):
        Resolver(db_conn, cuenta_default='999')


# ─── Resolución de clientes ───────────────────────────────────────────────


def test_resolucion_cliente_ok(db_conn):
    upsert_cliente_mapping(db_conn, codigo='CLI001', nombre='Alpha SL')
    set_subcuenta_cliente(db_conn, 'CLI001', '430001')
    marcar_cliente_revisado(db_conn, 'CLI001')

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_cliente('CLI001')

    assert resultado.subcuenta_a3 == '430001'
    assert resultado.nombre == 'Alpha SL'


def test_cliente_sin_subcuenta_lanza_error(db_conn):
    upsert_cliente_mapping(db_conn, codigo='CLI002', nombre='Beta')
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)

    with pytest.raises(ClienteSinSubcuentaError, match='Beta'):
        resolver.resolver_cliente('CLI002')


def test_cliente_no_sincronizado_lanza_error(db_conn):
    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    with pytest.raises(ClienteSinSubcuentaError, match='no existe'):
        resolver.resolver_cliente('CLI999')
