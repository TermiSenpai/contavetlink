"""Tests Fase 1 — motor de evaluación de filtros AND/OR.

El motor opera sobre la dataclass `Factura` — no toca DBFs ni nada externo.
Los tests construyen facturas sintéticas y verifican que la composición lógica
del árbol funciona en todas las combinaciones que la UI puede generar.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.sources.base import (
    Condicion,
    Factura,
    Filtros,
    OperadorCondicion,
    OperadorFiltro,
)
from app.sources.filtros import aplica_filtros


def _factura(
    *,
    codigo: str = 'FAC0000001',
    serie: str = 'A',
    cliente: str = 'CLI00001',
    fecha_iso: str = '2026-01-15',
    total: str = '100.00',
) -> Factura:
    return Factura(
        codigo=codigo,
        serie=serie,
        numero='000001',
        cliente_codigo=cliente,
        fecha=date.fromisoformat(fecha_iso),
        total_base=Decimal(total),
        total_con_iva=Decimal(total),
        ptsbase1=Decimal('0'), iva1=Decimal('0'), recequi1=Decimal('0'),
        ptsbase2=Decimal('0'), iva2=Decimal('0'), recequi2=Decimal('0'),
        ptsbase3=Decimal('0'), iva3=Decimal('0'), recequi3=Decimal('0'),
        retirpf=Decimal('0'),
        contabil=False,
    )


# ─── Composición del árbol ──────────────────────────────────────────────────


def test_filtro_vacio_devuelve_todo():
    assert aplica_filtros(Filtros(), _factura()) is True


def test_filtro_and_simple_se_cumple():
    filtros = Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion('fecha', OperadorCondicion.ENTRE, ('2026-01-01', '2026-01-31')),
            Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00001'),
        ],
    )
    assert aplica_filtros(filtros, _factura()) is True


def test_filtro_and_falla_si_alguna_condicion_no_se_cumple():
    filtros = Filtros(
        operador=OperadorFiltro.AND,
        condiciones=[
            Condicion('fecha', OperadorCondicion.ENTRE, ('2026-01-01', '2026-01-31')),
            Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00099'),
        ],
    )
    assert aplica_filtros(filtros, _factura()) is False


def test_filtro_or_simple_se_cumple_con_una_rama():
    filtros = Filtros(
        operador=OperadorFiltro.OR,
        condiciones=[
            Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00001'),
            Condicion('cliente', OperadorCondicion.IGUAL, 'CLI00002'),
        ],
    )
    assert aplica_filtros(filtros, _factura(cliente='CLI00002')) is True


def test_filtro_or_falla_si_ninguna_se_cumple():
    filtros = Filtros(
        operador=OperadorFiltro.OR,
        condiciones=[
            Condicion('serie', OperadorCondicion.IGUAL, 'B'),
            Condicion('serie', OperadorCondicion.IGUAL, 'C'),
        ],
    )
    assert aplica_filtros(filtros, _factura(serie='A')) is False


def test_filtro_anidado_and_or():
    """Reproduce el ejemplo del plan: enero 2026 AND (cliente1 OR cliente2)."""
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
    assert aplica_filtros(filtros, _factura(cliente='CLI00001')) is True
    assert aplica_filtros(filtros, _factura(cliente='CLI00002')) is True
    assert aplica_filtros(filtros, _factura(cliente='CLI00099')) is False


# ─── Operadores individuales ────────────────────────────────────────────────


def test_operador_entre_acepta_strings_iso():
    cond = Condicion('fecha', OperadorCondicion.ENTRE, ('2026-01-01', '2026-01-31'))
    f = Filtros(condiciones=[cond])
    assert aplica_filtros(f, _factura(fecha_iso='2026-01-15')) is True
    assert aplica_filtros(f, _factura(fecha_iso='2026-02-01')) is False


def test_operador_antes_de_y_despues_de():
    f_antes = Filtros(condiciones=[Condicion('fecha', OperadorCondicion.ANTES_DE, '2026-01-15')])
    f_despues = Filtros(condiciones=[Condicion('fecha', OperadorCondicion.DESPUES_DE, '2026-01-15')])
    assert aplica_filtros(f_antes, _factura(fecha_iso='2026-01-10')) is True
    assert aplica_filtros(f_antes, _factura(fecha_iso='2026-01-20')) is False
    assert aplica_filtros(f_despues, _factura(fecha_iso='2026-01-20')) is True


def test_operador_contiene_cliente_es_case_insensitive():
    cond = Condicion('cliente', OperadorCondicion.CONTIENE, 'cli000')
    f = Filtros(condiciones=[cond])
    assert aplica_filtros(f, _factura(cliente='CLI00001')) is True


def test_operador_no_igual():
    cond = Condicion('serie', OperadorCondicion.NO_IGUAL, 'B')
    f = Filtros(condiciones=[cond])
    assert aplica_filtros(f, _factura(serie='A')) is True
    assert aplica_filtros(f, _factura(serie='B')) is False


def test_operador_importe_mayor_que_acepta_string():
    cond = Condicion('importe', OperadorCondicion.MAYOR_QUE, '50')
    f = Filtros(condiciones=[cond])
    assert aplica_filtros(f, _factura(total='100.00')) is True
    assert aplica_filtros(f, _factura(total='25.00')) is False


def test_operador_importe_entre_normaliza_decimal():
    cond = Condicion('importe', OperadorCondicion.ENTRE, ('50', '150'))
    f = Filtros(condiciones=[cond])
    assert aplica_filtros(f, _factura(total='100.00')) is True
    assert aplica_filtros(f, _factura(total='200.00')) is False


# ─── Validación de entrada ──────────────────────────────────────────────────


def test_campo_invalido_lanza_value_error():
    cond = Condicion('campo_inventado', OperadorCondicion.IGUAL, 'X')
    with pytest.raises(ValueError, match='Campo de filtro no soportado'):
        aplica_filtros(Filtros(condiciones=[cond]), _factura())


def test_campo_resolucion_se_ignora_en_este_nivel():
    """`resolucion` se aplica más tarde sobre datos enriquecidos del intermediario."""
    cond = Condicion('resolucion', OperadorCondicion.IGUAL, 'verde')
    assert aplica_filtros(Filtros(condiciones=[cond]), _factura()) is True


def test_operador_entre_con_valor_invalido():
    cond = Condicion('fecha', OperadorCondicion.ENTRE, '2026-01-01')
    with pytest.raises(ValueError, match='ENTRE requiere'):
        aplica_filtros(Filtros(condiciones=[cond]), _factura())
