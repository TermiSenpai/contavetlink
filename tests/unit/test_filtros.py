"""Tests Fase 1 — composición de filtros AND/OR."""
from __future__ import annotations

import pytest

from app.sources.base import (
    Condicion,
    Filtros,
    OperadorCondicion,
    OperadorFiltro,
)


pytestmark = pytest.mark.skip(reason="Fase 1 — pendiente de implementación")


def test_filtro_and_simple():
    filtros = Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion('fecha', OperadorCondicion.ENTRE, ('2026-01-01', '2026-01-31')),
            Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00001'),
        ],
    )
    assert filtros.operador == OperadorFiltro.AND
    assert len(filtros.condiciones) == 2


def test_filtro_or_simple():
    pass


def test_filtro_anidado():
    filtros = Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion('fecha', OperadorCondicion.ENTRE, ('2026-01-01', '2026-01-31')),
            Filtros(
                operador=OperadorFiltro.OR,
                condiciones=[
                    Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00001'),
                    Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00002'),
                ],
            ),
        ],
    )
    assert isinstance(filtros.condiciones[1], Filtros)


def test_filtro_vacio_devuelve_todo():
    pass
