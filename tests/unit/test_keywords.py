"""Tests Fase 2 — motor de keyword matching + CRUD."""
from __future__ import annotations

import pytest

from app.mapping.keywords import (
    Keyword,
    add_keyword,
    delete_keyword,
    load_keywords,
    match,
    update_keyword,
)
from app.mapping.store import SubcuentaInvalidaError


def _kw(
    id: int = 1,
    keyword: str = 'cert',
    cuenta: str = '700001',
    prioridad: int = 10,
    activo: bool = True,
) -> Keyword:
    return Keyword(
        id=id, keyword=keyword, cuenta_a3=cuenta,
        prioridad=prioridad, activo=activo,
    )


# ─── match() puro ──────────────────────────────────────────────────────────


def test_keyword_match_case_insensitive():
    kws = [_kw(keyword='CERT')]
    assert match('certificado de salud', kws) == kws[0]
    assert match('CERTIFICADO DE SALUD', kws) == kws[0]


def test_keyword_prioridad():
    """Con varias keywords que hacen match, gana la que llega primero
    (el caller ordena por prioridad DESC con `load_keywords`)."""
    alta = _kw(id=1, keyword='cert', cuenta='700001', prioridad=50)
    baja = _kw(id=2, keyword='salud', cuenta='755001', prioridad=10)
    resultado = match('certificado de salud', [alta, baja])
    assert resultado is alta


def test_keyword_sin_match_devuelve_none():
    kws = [_kw(keyword='chip')]
    assert match('certificado antirrabico', kws) is None


def test_keyword_inactiva_no_matchea():
    inactiva = _kw(keyword='cert', activo=False)
    assert match('certificado', [inactiva]) is None


def test_keyword_texto_vacio_devuelve_none():
    kws = [_kw(keyword='cert')]
    assert match('', kws) is None
    assert match(None, kws) is None  # type: ignore[arg-type]


def test_keyword_lista_vacia_devuelve_none():
    assert match('texto cualquiera', []) is None


# ─── CRUD sobre SQLite ─────────────────────────────────────────────────────


def test_add_keyword_valida_subcuenta(db_conn):
    with pytest.raises(SubcuentaInvalidaError):
        add_keyword(db_conn, keyword='chip', cuenta_a3='999999')


def test_add_keyword_rechaza_vacia(db_conn):
    with pytest.raises(ValueError, match='vacía'):
        add_keyword(db_conn, keyword='   ', cuenta_a3='700001')


def test_add_keyword_persiste_y_load_devuelve_ordenado(db_conn):
    add_keyword(db_conn, keyword='chip', cuenta_a3='700001', prioridad=10)
    add_keyword(db_conn, keyword='cert', cuenta_a3='755001', prioridad=50)
    add_keyword(db_conn, keyword='visita', cuenta_a3='700002', prioridad=30)

    cargadas = load_keywords(db_conn)
    assert [k.keyword for k in cargadas] == ['cert', 'visita', 'chip']


def test_add_keyword_unique(db_conn):
    add_keyword(db_conn, keyword='chip', cuenta_a3='700001')
    with pytest.raises(ValueError, match='ya existe'):
        add_keyword(db_conn, keyword='chip', cuenta_a3='755001')


def test_load_keywords_solo_activas_por_defecto(db_conn):
    add_keyword(db_conn, keyword='chip', cuenta_a3='700001')
    add_keyword(db_conn, keyword='cert', cuenta_a3='755001', activo=False)
    activas = load_keywords(db_conn)
    assert len(activas) == 1
    assert activas[0].keyword == 'chip'

    todas = load_keywords(db_conn, solo_activos=False)
    assert len(todas) == 2


def test_update_keyword(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001', prioridad=10)
    update_keyword(db_conn, kw_id, prioridad=80, activo=False)
    todas = load_keywords(db_conn, solo_activos=False)
    assert todas[0].prioridad == 80
    assert todas[0].activo is False


def test_update_keyword_no_existe(db_conn):
    with pytest.raises(KeyError):
        update_keyword(db_conn, 9999, prioridad=5)


def test_update_keyword_valida_subcuenta(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001')
    with pytest.raises(SubcuentaInvalidaError):
        update_keyword(db_conn, kw_id, cuenta_a3='123abc')


def test_update_keyword_rechaza_texto_vacio(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001')
    with pytest.raises(ValueError, match='vacía'):
        update_keyword(db_conn, kw_id, keyword='   ')


def test_update_keyword_campos_individuales(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001', prioridad=10)
    update_keyword(db_conn, kw_id, keyword='microchip')
    update_keyword(db_conn, kw_id, cuenta_a3='755001')
    resultado = load_keywords(db_conn)[0]
    assert resultado.keyword == 'microchip'
    assert resultado.cuenta_a3 == '755001'


def test_update_keyword_sin_cambios_es_noop(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001', prioridad=10)
    update_keyword(db_conn, kw_id)  # no-op
    resultado = load_keywords(db_conn)[0]
    assert resultado.keyword == 'chip'
    assert resultado.prioridad == 10


def test_delete_keyword(db_conn):
    kw_id = add_keyword(db_conn, keyword='chip', cuenta_a3='700001')
    delete_keyword(db_conn, kw_id)
    assert load_keywords(db_conn) == []


def test_delete_keyword_no_existe(db_conn):
    with pytest.raises(KeyError):
        delete_keyword(db_conn, 9999)
