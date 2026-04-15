"""Tests Fase 3 — builder de registros SUENLACE."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.exporter.builder import (
    Builder,
    CuadreError,
    FacturaYaExportadaError,
    OrdenCabecera,
    OrdenDetalle,
    RegistroCabecera,
    TipoRegistro,
)
from app.mapping.resolver import ClienteSinSubcuentaError, Resolver
from app.mapping.store import (
    marcar_cliente_revisado,
    set_subcuenta_cliente,
    upsert_cliente_mapping,
)
from app.sources.base import Factura, LineaFactura

COD_EMPRESA = 42
CUENTA_VENTAS_DEF = '700001'


# ─── Helpers ──────────────────────────────────────────────────────────────


def _seed_cliente(conn, codigo='CLI001', nombre='Alpha SL', subcuenta='430001'):
    upsert_cliente_mapping(conn, codigo=codigo, nombre=nombre)
    set_subcuenta_cliente(conn, codigo, subcuenta)
    marcar_cliente_revisado(conn, codigo)


def _builder(conn):
    resolver = Resolver(conn, cuenta_default=CUENTA_VENTAS_DEF)
    return Builder(
        conn,
        resolver=resolver,
        cod_empresa=COD_EMPRESA,
        cuenta_ventas_def=CUENTA_VENTAS_DEF,
    )


def _factura(
    *,
    codigo='FAC0000001',
    cliente='CLI001',
    ptsbases=(Decimal('100.00'), Decimal('0'), Decimal('0')),
    ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
    recequis=(Decimal('0'), Decimal('0'), Decimal('0')),
    retirpf=Decimal('0'),
    total=Decimal('121.00'),
    lineas: list[LineaFactura] | None = None,
) -> Factura:
    return Factura(
        codigo=codigo,
        serie='A',
        numero='000001',
        cliente_codigo=cliente,
        fecha=date(2026, 1, 15),
        total_base=sum(ptsbases, Decimal('0')),
        total_con_iva=total,
        ptsbase1=ptsbases[0], iva1=ivas[0], recequi1=recequis[0],
        ptsbase2=ptsbases[1], iva2=ivas[1], recequi2=recequis[1],
        ptsbase3=ptsbases[2], iva3=ivas[2], recequi3=recequis[2],
        retirpf=retirpf,
        contabil=False,
        lineas=lineas or [],
    )


# ─── Cabecera + detalles ──────────────────────────────────────────────────


def test_factura_un_iva_genera_cabecera_y_un_detalle(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura()

    resultado = builder.construir_registros(factura)

    assert isinstance(resultado.cabecera, RegistroCabecera)
    assert resultado.cabecera.tipreg == TipoRegistro.CABECERA
    assert resultado.cabecera.orden == OrdenCabecera.INICIAL
    assert resultado.cabecera.cuenta == '430001'
    assert resultado.cabecera.descuenta == 'Alpha SL'
    assert resultado.cabecera.numfac == 'A000001'
    assert resultado.cabecera.fecha == '20260115'
    assert resultado.cabecera.importe == Decimal('121.00')
    assert len(resultado.detalles) == 1


def test_factura_dos_iva_genera_cabecera_y_dos_detalles(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    # 100 al 21% + 50 al 10% = 150 base, 21 + 5 = 26 iva, total 176
    factura = _factura(
        ptsbases=(Decimal('100.00'), Decimal('50.00'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('0')),
        total=Decimal('176.00'),
    )
    resultado = builder.construir_registros(factura)
    assert len(resultado.detalles) == 2


def test_factura_tres_iva_genera_tres_detalles(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    total = (
        Decimal('100') * Decimal('1.21')
        + Decimal('50') * Decimal('1.10')
        + Decimal('25') * Decimal('1.04')
    )
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('50'), Decimal('25')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('4')),
        total=total,
    )
    resultado = builder.construir_registros(factura)
    assert len(resultado.detalles) == 3


def test_ultimo_detalle_orden_u(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('50'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('0')),
        total=Decimal('100') * Decimal('1.21') + Decimal('50') * Decimal('1.10'),
    )
    resultado = builder.construir_registros(factura)
    assert resultado.detalles[-1].orden == OrdenDetalle.ULTIMO


def test_detalles_intermedios_orden_m(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('50'), Decimal('25')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('4')),
        total=(
            Decimal('100') * Decimal('1.21')
            + Decimal('50') * Decimal('1.10')
            + Decimal('25') * Decimal('1.04')
        ),
    )
    resultado = builder.construir_registros(factura)
    assert resultado.detalles[0].orden == OrdenDetalle.INTERMEDIO
    assert resultado.detalles[1].orden == OrdenDetalle.INTERMEDIO
    assert resultado.detalles[-1].orden == OrdenDetalle.ULTIMO


def test_ptsbase_cero_no_genera_detalle(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('10'), Decimal('4')),
        total=Decimal('121.00'),
    )
    resultado = builder.construir_registros(factura)
    assert len(resultado.detalles) == 1
    assert resultado.detalles[0].por_iva == Decimal('21.00')


# ─── Cuadre ────────────────────────────────────────────────────────────────


def test_cuadre_base_mas_iva_tolerancia_002(db_conn):
    """sum(bases) + sum(cuotas) ≈ TOTCONIVA con tolerancia 0,02€."""
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    # 100 base + 21 iva = 121 exacto. Ponemos total = 121.01 → diff 0.01 ≤ 0.02 ✓
    factura_dentro = _factura(total=Decimal('121.01'))
    builder.construir_registros(factura_dentro)  # no lanza

    # total = 121.10 → diff 0.10 > 0.02 ✗
    factura_fuera = _factura(total=Decimal('121.10'))
    with pytest.raises(CuadreError, match='cuadre fuera de tolerancia'):
        builder.construir_registros(factura_fuera)


def test_cuadre_con_recargo_equivalencia(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    # base 100, iva 21, rec 5.2 → total 126.20
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        recequis=(Decimal('5.2'), Decimal('0'), Decimal('0')),
        total=Decimal('126.20'),
    )
    builder.construir_registros(factura)  # cuadra exacto


def test_cuadre_con_retencion_irpf(db_conn):
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    # base 100, iva 21, retirpf 15% → 100 + 21 - 15 = 106
    factura = _factura(
        ptsbases=(Decimal('100'), Decimal('0'), Decimal('0')),
        ivas=(Decimal('21'), Decimal('0'), Decimal('0')),
        retirpf=Decimal('15'),
        total=Decimal('106.00'),
    )
    builder.construir_registros(factura)


def test_cuadre_tolerancia_configurable(db_conn):
    """El builder acepta una tolerancia de cuadre custom para tests/dev data."""
    from app.mapping.resolver import Resolver
    _seed_cliente(db_conn)
    resolver = Resolver(db_conn, cuenta_default=CUENTA_VENTAS_DEF)
    # Tolerancia 0,50€ — admite facturas con dev data de bases enteras
    builder = Builder(
        db_conn, resolver=resolver, cod_empresa=42,
        cuenta_ventas_def=CUENTA_VENTAS_DEF,
        cuadre_tolerancia=Decimal('0.50'),
    )
    # 100 base + 21 iva = 121; total = 121.49 → diff 0.49 ≤ 0.50 ✓
    factura_dentro = _factura(total=Decimal('121.49'))
    builder.construir_registros(factura_dentro)  # no lanza

    # total = 121.51 → diff 0.51 > 0.50 ✗
    factura_fuera = _factura(total=Decimal('121.51'))
    with pytest.raises(CuadreError):
        builder.construir_registros(factura_fuera)


def test_cuadre_tolerancia_default_es_002(db_conn):
    """Sin override, el builder usa la tolerancia del plan (0,02€)."""
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    assert builder.cuadre_tolerancia == Decimal('0.02')


# ─── Errores ───────────────────────────────────────────────────────────────


def test_cliente_sin_subcuenta_error(db_conn):
    upsert_cliente_mapping(db_conn, codigo='CLI001', nombre='Sin subcuenta')
    builder = _builder(db_conn)
    factura = _factura()
    with pytest.raises(ClienteSinSubcuentaError):
        builder.construir_registros(factura)


def test_cliente_no_sincronizado_error(db_conn):
    builder = _builder(db_conn)
    factura = _factura(cliente='CLI999')
    with pytest.raises(ClienteSinSubcuentaError, match='no existe'):
        builder.construir_registros(factura)


def test_factura_ya_exportada_error(db_conn):
    _seed_cliente(db_conn)
    # Simular una exportación previa
    db_conn.execute(
        """INSERT INTO exportaciones
           (fecha_export, fecha_desde, fecha_hasta, num_facturas,
            dat_fichero, dat_hash, app_version)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ('2026-01-01', '2026-01-01', '2026-01-31', 1, '/tmp/x.dat', 'h', '0.1.0'),
    )
    db_conn.execute(
        """INSERT INTO exportaciones_detalle
           (exportacion_id, codigo_factura, cliente_gesdai,
            subcuenta_a3, total_coniva, resolucion_tipo)
           VALUES (1, ?, ?, ?, ?, ?)""",
        ('FAC0000001', 'CLI001', '430001', 121.0, 'mapping'),
    )

    builder = _builder(db_conn)
    with pytest.raises(FacturaYaExportadaError, match='FAC0000001'):
        builder.construir_registros(_factura())


def test_cod_empresa_fuera_de_rango():
    with pytest.raises(ValueError, match='fuera de rango'):
        Builder(
            conn=None,
            resolver=None,
            cod_empresa=0,
            cuenta_ventas_def='700001',
        )
    with pytest.raises(ValueError, match='fuera de rango'):
        Builder(
            conn=None,
            resolver=None,
            cod_empresa=100000,
            cuenta_ventas_def='700001',
        )


# ─── Resolución por línea (side-effect para tracking) ────────────────────


def test_resolver_se_llama_por_linea(db_conn):
    """El builder debe dejar rastro de resolución en mappings_articulos por
    cada línea — Fase 4 lo usa para pintar el semáforo."""
    _seed_cliente(db_conn)
    builder = _builder(db_conn)
    factura = _factura(
        lineas=[
            LineaFactura(
                codigo_factura='FAC0000001', linea=1, articulo='CERT-SALUD',
                cantidad=Decimal('1'), precio=Decimal('100'),
                iva=Decimal('21'), total_linea=Decimal('100'),
            ),
        ],
    )
    resultado = builder.construir_registros(factura)
    assert len(resultado.tipos_resolucion) == 1

    from app.mapping.store import get_articulo_mapping
    fila = get_articulo_mapping(db_conn, 'CERT-SALUD')
    assert fila is not None  # persistido por el resolver
