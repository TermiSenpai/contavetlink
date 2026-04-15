"""Tests de validación contra la spec oficial SUENLACE.DAT.

Ejecutan sobre un DAT generado y verifican estructura, longitud, encoding
y campos clave por posición. Estos tests son los que NUNCA pueden romperse
sin invalidar el output frente a a3ASESOR.

Spec completa en Sección 7 de PLAN_DESARROLLO.md.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.exporter.builder import (
    OrdenCabecera,
    OrdenDetalle,
    RegistroCabecera,
    RegistroDetalle,
    TipoRegistro,
)
from app.exporter.suenlace import (
    ENCODING,
    EOL,
    LONGITUD_REGISTRO,
    FormatoImporte,
    exportar,
)

pytestmark = pytest.mark.validation


# ─── Fixture: DAT canónico para todos los tests de validación ──────────────


@pytest.fixture
def dat_fichero(tmp_path):
    """Genera un SUENLACE.DAT canónico con 2 facturas (5 registros totales)
    para que los tests de validación tengan algo real contra lo que contrastar."""
    cab1 = RegistroCabecera(
        cod_empresa=42,
        fecha='20260115',
        tipreg=TipoRegistro.CABECERA,
        cuenta='430001',
        descuenta='Alpha SL',
        numfac='A000001',
        orden=OrdenCabecera.INICIAL,
        desfac='Fra A000001',
        importe=Decimal('121.00'),
    )
    det1 = RegistroDetalle(
        cod_empresa=42, fecha='20260115', tipreg=TipoRegistro.DETALLE,
        cuenta='700001', descuenta='Ventas 21%', numfac='A000001',
        orden=OrdenDetalle.ULTIMO, descrip='Fra A000001',
        base=Decimal('100.00'), por_iva=Decimal('21'), cuo_iva=Decimal('21.00'),
        por_rec=Decimal('0'), cuo_rec=Decimal('0'),
        por_ret=Decimal('0'), cuo_ret=Decimal('0'),
    )
    cab2 = RegistroCabecera(
        cod_empresa=42,
        fecha='20260116',
        tipreg=TipoRegistro.CABECERA,
        cuenta='430002',
        descuenta='Señor Núñez €',  # cp1252 edge
        numfac='A000002',
        orden=OrdenCabecera.INICIAL,
        desfac='Fra A000002',
        importe=Decimal('176.00'),
    )
    det2a = RegistroDetalle(
        cod_empresa=42, fecha='20260116', tipreg=TipoRegistro.DETALLE,
        cuenta='700001', descuenta='Ventas 21%', numfac='A000002',
        orden=OrdenDetalle.INTERMEDIO, descrip='Fra A000002',
        base=Decimal('100.00'), por_iva=Decimal('21'), cuo_iva=Decimal('21.00'),
        por_rec=Decimal('0'), cuo_rec=Decimal('0'),
        por_ret=Decimal('0'), cuo_ret=Decimal('0'),
    )
    det2b = RegistroDetalle(
        cod_empresa=42, fecha='20260116', tipreg=TipoRegistro.DETALLE,
        cuenta='700001', descuenta='Ventas 10%', numfac='A000002',
        orden=OrdenDetalle.ULTIMO, descrip='Fra A000002',
        base=Decimal('50.00'), por_iva=Decimal('10'), cuo_iva=Decimal('5.00'),
        por_rec=Decimal('0'), cuo_rec=Decimal('0'),
        por_ret=Decimal('0'), cuo_ret=Decimal('0'),
    )
    ruta = tmp_path / 'SUENLACE.DAT'
    exportar(
        [(cab1, [det1]), (cab2, [det2a, det2b])],
        ruta,
        FormatoImporte.A_IMPLICITO,
    )
    return ruta


# ─── Constantes ────────────────────────────────────────────────────────────


def test_constantes_spec():
    """Las constantes derivadas del spec no pueden cambiar accidentalmente."""
    assert LONGITUD_REGISTRO == 254
    assert ENCODING == 'cp1252'
    assert EOL == '\r\n'


# ─── Estructura del fichero ────────────────────────────────────────────────


def test_todos_los_registros_miden_254_chars(dat_fichero):
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    assert len(lineas) == 5  # 2 cabeceras + 3 detalles
    for i, linea in enumerate(lineas):
        assert len(linea) == LONGITUD_REGISTRO, (
            f"línea {i+1} mide {len(linea)} bytes, esperado {LONGITUD_REGISTRO}"
        )


def test_separador_linea_es_crlf(dat_fichero):
    """El fichero debe usar CRLF (\\r\\n) — nunca LF solo."""
    contenido = dat_fichero.read_bytes()
    assert b'\r\n' in contenido
    # No debe haber ningún \n huérfano (sin \r delante)
    for i, byte in enumerate(contenido):
        if byte == 0x0A and (i == 0 or contenido[i - 1] != 0x0D):
            pytest.fail(f"LF huérfano en byte {i}")


def test_encoding_cp1252(dat_fichero):
    """El fichero debe decodificar limpio en cp1252 y tener caracteres específicos."""
    contenido = dat_fichero.read_bytes()
    # 'ñ' en cp1252 = 0xF1 (en UTF-8 sería 0xC3 0xB1)
    assert b'\xf1' in contenido
    # '€' en cp1252 = 0x80 (en UTF-8 sería 0xE2 0x82 0xAC)
    assert b'\x80' in contenido
    # Y decodifica completo sin errores
    contenido.decode(ENCODING)


def test_tipreg_en_posicion_15(dat_fichero):
    """Posición 15 (1-indexed) debe ser '1' (cabecera) o '9' (detalle)."""
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    tipregs = [chr(linea[14]) for linea in lineas]
    assert tipregs == ['1', '9', '1', '9', '9']


def test_cuenta_padding_12_chars_en_posicion_16(dat_fichero):
    """Posición 16-27 (1-indexed) = cuenta, siempre 12 chars con padding."""
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    # Cabecera 1: cuenta cliente 430001
    assert lineas[0][15:27].decode(ENCODING) == '430001      '
    # Detalle 1: cuenta ingreso 700001
    assert lineas[1][15:27].decode(ENCODING) == '700001      '


def test_codemp_5_digitos_en_pos_2(dat_fichero):
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    for linea in lineas:
        assert linea[1:6].decode(ENCODING) == '00042'


def test_moneda_e_en_pos_253(dat_fichero):
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    for linea in lineas:
        assert linea[252:253].decode(ENCODING) == 'E'


def test_orden_ultimo_detalle_por_factura_es_u(dat_fichero):
    contenido = dat_fichero.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    # Factura 1: cab(I) + det(U) — único detalle
    assert chr(lineas[0][68]) == 'I'
    assert chr(lineas[1][68]) == 'U'
    # Factura 2: cab(I) + det(M) + det(U)
    assert chr(lineas[2][68]) == 'I'
    assert chr(lineas[3][68]) == 'M'
    assert chr(lineas[4][68]) == 'U'
