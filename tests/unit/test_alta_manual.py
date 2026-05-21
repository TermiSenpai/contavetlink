"""Tests del alta manual de artículos/clientes y del match por NIF.

Cubre el flujo "ítem que vive en a3ASESOR pero no en GESDAI":

  · `crear_articulo_manual` y `crear_cliente_manual` insertan con
    `origen='manual'`, `revisado=1` y rechazan duplicados (clave/código
    o cuenta ya asignada).
  · `eliminar_*_manual` sólo borra filas con `origen='manual'`. Una fila
    sincronizada desde GESDAI lanza `OrigenInvalidoError` — proteger esto
    es crítico porque las filas GESDAI deben vivir mientras GESDAI las
    tenga.
  · El `Resolver` casa por NIF: cuando un cliente GESDAI no tiene
    subcuenta pero su NIF coincide con un cliente manual, se usa la
    subcuenta y el nombre del manual.
"""
from __future__ import annotations

import pytest

from app.mapping.resolver import (
    ClienteSinSubcuentaError,
    Resolver,
)
from app.mapping.store import (
    ORIGEN_GESDAI,
    ORIGEN_MANUAL,
    CodigoDuplicadoError,
    CuentaDuplicadaError,
    OrigenInvalidoError,
    SubcuentaInvalidaError,
    crear_articulo_manual,
    crear_cliente_manual,
    eliminar_articulo_manual,
    eliminar_cliente_manual,
    find_cliente_manual_por_nif,
    get_articulo_mapping,
    get_cliente_mapping,
    upsert_articulo_mapping,
    upsert_cliente_mapping,
)

CUENTA_DEFAULT = '700001'


# ─── Alta manual de artículos ──────────────────────────────────────────────


def test_crear_articulo_manual_inserta_revisado(db_conn):
    crear_articulo_manual(
        db_conn,
        clave='MAN-CHIP',
        descripcion='Chip extra promocional',
        cuenta_a3='700100',
    )

    fila = get_articulo_mapping(db_conn, 'MAN-CHIP')
    assert fila is not None
    assert fila['descripcion'] == 'Chip extra promocional'
    assert fila['cuenta_a3'] == '700100'
    assert fila['revisado'] == 1
    assert fila['origen'] == ORIGEN_MANUAL


def test_crear_articulo_manual_rechaza_clave_duplicada(db_conn):
    upsert_articulo_mapping(db_conn, clave='CHIP', descripcion='Microchip')
    with pytest.raises(CodigoDuplicadoError):
        crear_articulo_manual(
            db_conn,
            clave='CHIP',
            descripcion='Otro',
            cuenta_a3='700200',
        )


def test_crear_articulo_manual_rechaza_cuenta_duplicada(db_conn):
    crear_articulo_manual(
        db_conn, clave='MAN-A', descripcion='A', cuenta_a3='700100',
    )
    with pytest.raises(CuentaDuplicadaError):
        crear_articulo_manual(
            db_conn, clave='MAN-B', descripcion='B', cuenta_a3='700100',
        )


def test_crear_articulo_manual_rechaza_cuenta_invalida(db_conn):
    with pytest.raises(SubcuentaInvalidaError):
        crear_articulo_manual(
            db_conn, clave='X', descripcion='X', cuenta_a3='123456',
        )


def test_crear_articulo_manual_rechaza_campos_vacios(db_conn):
    with pytest.raises(ValueError):
        crear_articulo_manual(
            db_conn, clave='', descripcion='x', cuenta_a3='700100',
        )
    with pytest.raises(ValueError):
        crear_articulo_manual(
            db_conn, clave='X', descripcion='   ', cuenta_a3='700100',
        )


def test_eliminar_articulo_manual_borra(db_conn):
    crear_articulo_manual(
        db_conn, clave='MAN-X', descripcion='X', cuenta_a3='700101',
    )
    eliminar_articulo_manual(db_conn, 'MAN-X')
    assert get_articulo_mapping(db_conn, 'MAN-X') is None


def test_eliminar_articulo_manual_protege_origen_gesdai(db_conn):
    """Las filas sincronizadas desde GESDAI no se pueden borrar manualmente."""
    upsert_articulo_mapping(db_conn, clave='CHIP', descripcion='Microchip')
    fila = get_articulo_mapping(db_conn, 'CHIP')
    assert fila['origen'] == ORIGEN_GESDAI

    with pytest.raises(OrigenInvalidoError):
        eliminar_articulo_manual(db_conn, 'CHIP')

    assert get_articulo_mapping(db_conn, 'CHIP') is not None


# ─── Alta manual de clientes ───────────────────────────────────────────────


def test_crear_cliente_manual_inserta_revisado(db_conn):
    crear_cliente_manual(
        db_conn,
        codigo='MAN001',
        nombre='APELLIDOS, NOMBRE',
        subcuenta_a3='430999',
        nif='12345678A',
    )

    fila = get_cliente_mapping(db_conn, 'MAN001')
    assert fila is not None
    assert fila['nombre'] == 'APELLIDOS, NOMBRE'
    assert fila['subcuenta_a3'] == '430999'
    assert fila['nif'] == '12345678A'
    assert fila['revisado'] == 1
    assert fila['origen'] == ORIGEN_MANUAL


def test_crear_cliente_manual_rechaza_codigo_duplicado(db_conn):
    upsert_cliente_mapping(db_conn, codigo='00000001', nombre='Existente')
    with pytest.raises(CodigoDuplicadoError):
        crear_cliente_manual(
            db_conn,
            codigo='00000001',
            nombre='Otro',
            subcuenta_a3='430500',
        )


def test_crear_cliente_manual_rechaza_subcuenta_duplicada(db_conn):
    crear_cliente_manual(
        db_conn, codigo='M1', nombre='A', subcuenta_a3='430500',
    )
    with pytest.raises(CuentaDuplicadaError):
        crear_cliente_manual(
            db_conn, codigo='M2', nombre='B', subcuenta_a3='430500',
        )


def test_eliminar_cliente_manual_protege_origen_gesdai(db_conn):
    upsert_cliente_mapping(db_conn, codigo='00000001', nombre='Existente')
    with pytest.raises(OrigenInvalidoError):
        eliminar_cliente_manual(db_conn, '00000001')


# ─── Match por NIF en el Resolver ─────────────────────────────────────────


def test_find_cliente_manual_por_nif_normaliza(db_conn):
    crear_cliente_manual(
        db_conn,
        codigo='MAN001',
        nombre='APELLIDOS, NOMBRE',
        subcuenta_a3='430999',
        nif='12345678a',
    )

    fila = find_cliente_manual_por_nif(db_conn, '  12345678A  ')
    assert fila is not None
    assert fila['codigo_gesdai'] == 'MAN001'

    assert find_cliente_manual_por_nif(db_conn, '') is None
    assert find_cliente_manual_por_nif(db_conn, '00000000Z') is None


def test_find_cliente_manual_ignora_clientes_gesdai(db_conn):
    """El fallback es sólo para clientes manuales — los GESDAI ya se resuelven
    por código directamente."""
    upsert_cliente_mapping(
        db_conn, codigo='00000001', nombre='X', nif='12345678A',
    )
    assert find_cliente_manual_por_nif(db_conn, '12345678A') is None


def test_resolver_cliente_cae_a_manual_por_nif(db_conn):
    """Cliente GESDAI sin subcuenta + NIF que casa con manual → usa manual."""
    upsert_cliente_mapping(
        db_conn, codigo='00000010', nombre='GESDAI NAME', nif='12345678A',
    )
    crear_cliente_manual(
        db_conn,
        codigo='MAN001',
        nombre='A3 NAME',
        subcuenta_a3='430999',
        nif='12345678A',
    )

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_cliente('00000010')

    assert resultado.subcuenta_a3 == '430999'
    assert resultado.nombre == 'A3 NAME'


def test_resolver_cliente_subcuenta_propia_gana_a_match_nif(db_conn):
    """Si el cliente GESDAI ya tiene subcuenta, se usa la suya — el NIF no
    se consulta."""
    upsert_cliente_mapping(
        db_conn,
        codigo='00000010',
        nombre='GESDAI NAME',
        nif='12345678A',
        subcuenta_a3='430010',
    )
    crear_cliente_manual(
        db_conn,
        codigo='MAN001',
        nombre='A3 NAME',
        subcuenta_a3='430999',
        nif='12345678A',
    )

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    resultado = resolver.resolver_cliente('00000010')

    assert resultado.subcuenta_a3 == '430010'
    assert resultado.nombre == 'GESDAI NAME'


def test_resolver_cliente_lanza_si_ni_subcuenta_ni_match_nif(db_conn):
    upsert_cliente_mapping(
        db_conn, codigo='00000010', nombre='X', nif='99999999Z',
    )

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    with pytest.raises(ClienteSinSubcuentaError):
        resolver.resolver_cliente('00000010')


def test_resolver_cliente_sin_nif_no_intenta_match(db_conn):
    upsert_cliente_mapping(db_conn, codigo='00000010', nombre='X', nif=None)
    crear_cliente_manual(
        db_conn, codigo='MAN001', nombre='Y', subcuenta_a3='430999', nif=None,
    )

    resolver = Resolver(db_conn, cuenta_default=CUENTA_DEFAULT)
    with pytest.raises(ClienteSinSubcuentaError):
        resolver.resolver_cliente('00000010')
