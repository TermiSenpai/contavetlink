"""Tests: facturas con importes negativos (rectificativas informales).

COLVET ocasionalmente "rectifica" una factura emitiendo un ingreso en
negativo en lugar de seguir el flujo formal de factura rectificativa.
Estos tests verifican que el pipeline completo (cuadre → builder →
SUENLACE) soporta importes negativos sin perder datos.

Garantías cubiertas:

  · `_validar_cuadre` soporta negativos (la fórmula es lineal).
  · `format_num` soporta negativos en formatos A y B (anchos exactos).
  · `_construir_detalles` emite un detalle por cada tramo con `base != 0`,
    incluidos los negativos — antes filtraba `> 0` y descartaba en
    silencio las rectificativas informales (bug corregido).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.exporter.builder import Builder
from app.exporter.suenlace import (
    LONGITUD_REGISTRO,
    FormatoImporte,
    format_cabecera,
    format_detalle,
    format_num,
)
from app.mapping.resolver import Resolver
from app.mapping.store import (
    marcar_cliente_revisado,
    set_subcuenta_cliente,
    upsert_cliente_mapping,
)
from app.sources.base import Factura

CUENTA_DEFAULT = '700001'
COD_EMPRESA = 42


# ─── Helpers ──────────────────────────────────────────────────────────────


def _seed_cliente(conn, codigo='CLI001'):
    upsert_cliente_mapping(conn, codigo=codigo, nombre='Alpha SL')
    set_subcuenta_cliente(conn, codigo, '430001')
    marcar_cliente_revisado(conn, codigo)


def _builder(conn):
    resolver = Resolver(conn, cuenta_default=CUENTA_DEFAULT)
    return Builder(
        conn, resolver=resolver,
        cod_empresa=COD_EMPRESA, cuenta_ventas_def=CUENTA_DEFAULT,
    )


def _factura(
    *,
    codigo='REC0001',
    ptsbases=(Decimal('-100.00'), Decimal('0'), Decimal('0')),
    ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
    total=Decimal('-121.00'),
) -> Factura:
    return Factura(
        codigo=codigo,
        serie='R',
        numero='000001',
        cliente_codigo='CLI001',
        fecha=date(2026, 1, 15),
        total_base=sum(ptsbases, Decimal('0')),
        total_con_iva=total,
        ptsbase1=ptsbases[0], iva1=ivas[0], recequi1=Decimal('0'),
        ptsbase2=ptsbases[1], iva2=ivas[1], recequi2=Decimal('0'),
        ptsbase3=ptsbases[2], iva3=ivas[2], recequi3=Decimal('0'),
        retirpf=Decimal('0'),
        contabil=False,
        lineas=[],
    )


# ═══════════════════════════════════════════════════════════════════════════
#   CUADRE — la fórmula es lineal, los negativos no la rompen
# ═══════════════════════════════════════════════════════════════════════════


def test_cuadre_acepta_factura_totalmente_negativa(db_conn):
    """Un -100 base + -21 IVA = -121 total cuadra exactamente."""
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('-100.00'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        total=Decimal('-121.00'),
    )

    # No debe lanzar CuadreError
    builder._validar_cuadre(factura)


def test_cuadre_detecta_factura_negativa_mal_cuadrada(db_conn):
    """Una rectificativa mal grabada (total descuadrado) sigue fallando el
    cuadre — el signo no debe relajar la validación contable."""
    from app.exporter.builder import CuadreError

    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('-100.00'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        total=Decimal('-100.00'),  # debería ser -121, falta el IVA
    )

    with pytest.raises(CuadreError):
        builder._validar_cuadre(factura)


# ═══════════════════════════════════════════════════════════════════════════
#   FORMAT_NUM — anchos exactos para negativos
# ═══════════════════════════════════════════════════════════════════════════


def test_format_num_a_implicito_negativo_anchura_exacta():
    """Formato A con -12,50 € → '-0000000001250' (14 chars con el '-')."""
    resultado = format_num(Decimal('-12.50'), 14, FormatoImporte.A_IMPLICITO)
    assert len(resultado) == 14
    assert resultado == '-0000000001250'


def test_format_num_b_explicito_negativo_anchura_exacta():
    """Formato B con -12,50 € → '-0000000012.50' (14 chars con el '-')."""
    resultado = format_num(Decimal('-12.50'), 14, FormatoImporte.B_EXPLICITO)
    assert len(resultado) == 14
    assert resultado == '-0000000012.50'


def test_format_num_negativo_que_no_cabe_lanza():
    """Si el '-' empuja el número fuera de ancho, format_num debe protestar
    para que no se descuadre la línea (defensa en profundidad — el spec
    de COLVET no debería tener importes así de grandes nunca, pero queremos
    fallar ruidosamente en lugar de generar un DAT corrupto)."""
    # 14 chars de ancho, formato A: max representable -999999999999 (12 dígitos + '-' = 13… ok)
    # Forzamos un valor que NO cabe: 100.000.000.000,00 € → escala 10^16 chars
    with pytest.raises(ValueError, match='no cabe'):
        format_num(Decimal('-99999999999999.99'), 14, FormatoImporte.A_IMPLICITO)


# ═══════════════════════════════════════════════════════════════════════════
#   LÍNEAS SUENLACE — 254 chars exactos también con negativos
# ═══════════════════════════════════════════════════════════════════════════


def test_cabecera_con_importe_negativo_254_chars():
    """La cabecera de una rectificativa informal sigue siendo 254 chars."""
    from app.exporter.builder import OrdenCabecera, RegistroCabecera, TipoRegistro

    cab = RegistroCabecera(
        cod_empresa=42,
        fecha='20260115',
        tipreg=TipoRegistro.CABECERA,
        cuenta='430001',
        descuenta='Cliente Uno',
        numfac='R000001',
        orden=OrdenCabecera.INICIAL,
        desfac='Rectif R000001',
        importe=Decimal('-121.00'),
    )
    linea = format_cabecera(cab, FormatoImporte.A_IMPLICITO)
    assert len(linea) == LONGITUD_REGISTRO


def test_detalle_con_base_negativa_254_chars():
    """Un detalle con base negativa también respeta los 254 chars."""
    from app.exporter.builder import OrdenDetalle, RegistroDetalle, TipoRegistro

    det = RegistroDetalle(
        cod_empresa=42,
        fecha='20260115',
        tipreg=TipoRegistro.DETALLE,
        cuenta='700001',
        descuenta='Ventas 21%',
        numfac='R000001',
        orden=OrdenDetalle.ULTIMO,
        descrip='Rectif R000001',
        base=Decimal('-100.00'),
        por_iva=Decimal('21'),
        cuo_iva=Decimal('-21.00'),
        por_rec=Decimal('0'),
        cuo_rec=Decimal('0'),
        por_ret=Decimal('0'),
        cuo_ret=Decimal('0'),
    )
    linea = format_detalle(det, FormatoImporte.A_IMPLICITO)
    assert len(linea) == LONGITUD_REGISTRO


# ═══════════════════════════════════════════════════════════════════════════
#   BUILDER — el bug actual: bases negativas se descartan en silencio
# ═══════════════════════════════════════════════════════════════════════════


def test_builder_factura_totalmente_negativa_emite_un_detalle(db_conn):
    """Una factura rectificativa "informal" (un único tramo de IVA, todo
    en negativo) produce:
      - 1 cabecera con importe = -121,00
      - 1 detalle con base = -100,00 y cuo_iva = -21,00

    Test de regresión del bug original (filtro `base > 0` que descartaba
    los tramos negativos). Si alguien vuelve a meter `> 0`, este test lo
    detecta inmediatamente.
    """
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('-100.00'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        total=Decimal('-121.00'),
    )

    resultado = builder.construir_registros(factura)

    assert resultado.cabecera.importe == Decimal('-121.00')
    assert len(resultado.detalles) == 1
    assert resultado.detalles[0].base == Decimal('-100.00')
    assert resultado.detalles[0].cuo_iva == Decimal('-21.00')
    # El único detalle debe llevar orden='U' (último), no 'M'
    from app.exporter.builder import OrdenDetalle
    assert resultado.detalles[0].orden == OrdenDetalle.ULTIMO


def test_builder_factura_mixta_positivo_y_negativo(db_conn):
    """Una misma factura con dos tramos de IVA — uno positivo y otro
    negativo — produce un detalle por cada tramo distinto de cero.
    Caso raro pero posible: GESDAI permite grabar líneas de devolución
    parcial dentro de una factura ordinaria.
    """
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('100.00'), Decimal('-50.00'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('0')),
        # 100 + 21 - 50 - 5 = 66
        total=Decimal('66.00'),
    )

    resultado = builder.construir_registros(factura)

    assert len(resultado.detalles) == 2
    bases = sorted(d.base for d in resultado.detalles)
    assert bases == [Decimal('-50.00'), Decimal('100.00')]

    # El orden 'M' / 'U' se preserva — el último siempre lleva 'U'
    from app.exporter.builder import OrdenDetalle
    assert resultado.detalles[-1].orden == OrdenDetalle.ULTIMO
    assert resultado.detalles[0].orden == OrdenDetalle.INTERMEDIO


def test_builder_factura_negativa_dat_completo_round_trip(db_conn):
    """End-to-end: una rectificativa informal genera dos líneas SUENLACE
    de 254 chars cada una (cabecera + detalle), ambas serializables sin
    errores de encoding ni desbordamiento de campo."""
    from app.exporter.suenlace import format_cabecera, format_detalle

    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('-200.00'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        total=Decimal('-242.00'),
    )

    resultado = builder.construir_registros(factura)
    linea_cab = format_cabecera(resultado.cabecera, FormatoImporte.A_IMPLICITO)
    linea_det = format_detalle(resultado.detalles[0], FormatoImporte.A_IMPLICITO)

    assert len(linea_cab) == LONGITUD_REGISTRO
    assert len(linea_det) == LONGITUD_REGISTRO
    # El importe negativo debe aparecer en la línea (con signo '-')
    assert '-' in linea_cab
    assert '-' in linea_det
