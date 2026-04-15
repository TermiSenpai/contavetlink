"""Tests Fase 3 — formateo SUENLACE.DAT (longitud, encoding, formato).

Ver Sección 7 de PLAN_DESARROLLO.md para la especificación oficial.
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
    format_alfa,
    format_cabecera,
    format_detalle,
    format_num,
    preview,
)

# ─── Helpers ───────────────────────────────────────────────────────────────


def _cabecera(
    cod_empresa: int = 42,
    cuenta: str = '430001',
    descuenta: str = 'Cliente Uno',
    numfac: str = 'A000001',
    desfac: str = 'Fra A000001',
    importe: Decimal = Decimal('121.00'),
) -> RegistroCabecera:
    return RegistroCabecera(
        cod_empresa=cod_empresa,
        fecha='20260115',
        tipreg=TipoRegistro.CABECERA,
        cuenta=cuenta,
        descuenta=descuenta,
        numfac=numfac,
        orden=OrdenCabecera.INICIAL,
        desfac=desfac,
        importe=importe,
    )


def _detalle(
    cod_empresa: int = 42,
    cuenta: str = '700001',
    orden: OrdenDetalle = OrdenDetalle.ULTIMO,
    base: Decimal = Decimal('100.00'),
    por_iva: Decimal = Decimal('21'),
    cuo_iva: Decimal = Decimal('21.00'),
) -> RegistroDetalle:
    return RegistroDetalle(
        cod_empresa=cod_empresa,
        fecha='20260115',
        tipreg=TipoRegistro.DETALLE,
        cuenta=cuenta,
        descuenta='Ventas 21%',
        numfac='A000001',
        orden=orden,
        descrip='Fra A000001',
        base=base,
        por_iva=por_iva,
        cuo_iva=cuo_iva,
        por_rec=Decimal('0'),
        cuo_rec=Decimal('0'),
        por_ret=Decimal('0'),
        cuo_ret=Decimal('0'),
    )


# ─── format_num ────────────────────────────────────────────────────────────


def test_format_num_a_implicito():
    """12,50€ → '00000000001250' (escala implícita)."""
    assert format_num(Decimal('12.50'), 14, FormatoImporte.A_IMPLICITO) == '00000000001250'


def test_format_num_a_cero():
    assert format_num(Decimal('0'), 14, FormatoImporte.A_IMPLICITO) == '00000000000000'


def test_format_num_a_iva_5_chars():
    """IVA 21% en campo de 5 chars: '02100'."""
    assert format_num(Decimal('21'), 5, FormatoImporte.A_IMPLICITO) == '02100'


def test_format_num_a_redondea_medio():
    """12,505 → '00000000001251' (HALF_UP)."""
    assert format_num(Decimal('12.505'), 14, FormatoImporte.A_IMPLICITO) == '00000000001251'


def test_format_num_b_decimal_explicito():
    """12,50€ → '00000000012.50' (decimal explícito, 14 chars total)."""
    assert format_num(Decimal('12.50'), 14, FormatoImporte.B_EXPLICITO) == '00000000012.50'


def test_format_num_b_iva():
    assert format_num(Decimal('21'), 5, FormatoImporte.B_EXPLICITO) == '21.00'


def test_format_num_no_cabe_lanza():
    with pytest.raises(ValueError, match='no cabe'):
        format_num(Decimal('9999999999.99'), 5, FormatoImporte.A_IMPLICITO)


def test_format_num_negativo_a():
    """Valor negativo: signo fuera, dígitos zero-padded."""
    resultado = format_num(Decimal('-12.50'), 14, FormatoImporte.A_IMPLICITO)
    assert resultado.startswith('-')
    assert len(resultado) == 14
    assert resultado == '-0000000001250'


def test_format_num_negativo_b():
    """Valor negativo en formato B: Python mantiene el signo delante del cero-padding."""
    resultado = format_num(Decimal('-12.50'), 14, FormatoImporte.B_EXPLICITO)
    assert resultado.startswith('-')
    assert len(resultado) == 14
    # '-' + 9 zeros + '12.50' = 1 + 9 + 5 = 15... no; pad incluye el signo
    assert resultado == '-0000000012.50'


def test_format_num_negativo_b_pequeno():
    resultado = format_num(Decimal('-0.01'), 14, FormatoImporte.B_EXPLICITO)
    assert len(resultado) == 14
    assert resultado == '-0000000000.01'


def test_format_num_formato_desconocido():
    with pytest.raises(ValueError, match='Formato desconocido'):
        format_num(Decimal('10'), 14, 'FORMATO-RARO')  # type: ignore[arg-type]


def test_hash_sha256_streaming(tmp_path):
    """El helper interno que re-lee un DAT ya escrito produce el mismo sha."""
    from app.exporter.suenlace import _hash_sha256
    ruta = tmp_path / 'algo.dat'
    ruta.write_bytes(b'hola mundo')
    sha = _hash_sha256(ruta)
    assert len(sha) == 64
    # Determinismo
    assert _hash_sha256(ruta) == sha


# ─── format_alfa ───────────────────────────────────────────────────────────


def test_format_alfa_padea_derecha_por_defecto():
    """430001 → '430001      ' (espacios a la derecha hasta 12 chars)."""
    assert format_alfa('430001', 12) == '430001      '


def test_format_alfa_trunca_si_excede():
    assert format_alfa('NOMBRE MUY LARGO QUE SUPERA LOS 30', 30) == 'NOMBRE MUY LARGO QUE SUPERA LO'


def test_format_alfa_none_devuelve_espacios():
    assert format_alfa(None, 5) == '     '


def test_format_alfa_justifica_derecha():
    assert format_alfa('abc', 5, justificar='derecha') == '  abc'


def test_format_alfa_justificacion_invalida():
    with pytest.raises(ValueError):
        format_alfa('x', 5, justificar='centro')


# ─── Encoding cp1252 ───────────────────────────────────────────────────────


def test_encoding_cp1252_caracteres_especiales():
    """Caracteres como ñ, á, €, ü deben formatear sin error."""
    resultado = format_alfa('Señor Núñez €', 20)
    # Roundtrip cp1252 no debe perder info
    assert resultado.encode(ENCODING)  # no lanza
    assert 'Señor' in resultado


def test_encoding_cp1252_sustituye_chars_invalidos():
    """Emoji y CJK no caben en cp1252 → sustituidos por '?'."""
    resultado = format_alfa('Hola 🎉', 10)
    assert '🎉' not in resultado
    assert '?' in resultado


# ─── format_cabecera ───────────────────────────────────────────────────────


def test_registro_cabecera_exactamente_254_chars():
    linea = format_cabecera(_cabecera(), FormatoImporte.A_IMPLICITO)
    assert len(linea) == LONGITUD_REGISTRO


def test_cabecera_tipreg_en_posicion_15():
    linea = format_cabecera(_cabecera(), FormatoImporte.A_IMPLICITO)
    assert linea[14] == '1'  # pos 15 = index 14


def test_cabecera_cuenta_paddea_12_chars():
    """La subcuenta va en pos 16-27, con espacios a la derecha."""
    linea = format_cabecera(_cabecera(cuenta='430001'), FormatoImporte.A_IMPLICITO)
    assert linea[15:27] == '430001      '


def test_cabecera_orden_i_en_pos_69():
    linea = format_cabecera(_cabecera(), FormatoImporte.A_IMPLICITO)
    assert linea[68] == 'I'


def test_cabecera_moneda_e_en_pos_253():
    linea = format_cabecera(_cabecera(), FormatoImporte.A_IMPLICITO)
    assert linea[252] == 'E'


def test_cabecera_importe_formato_a():
    linea = format_cabecera(
        _cabecera(importe=Decimal('125.50')),
        FormatoImporte.A_IMPLICITO,
    )
    assert linea[99:113] == '00000000012550'


def test_cabecera_importe_formato_b():
    linea = format_cabecera(
        _cabecera(importe=Decimal('125.50')),
        FormatoImporte.B_EXPLICITO,
    )
    assert linea[99:113] == '00000000125.50'


# ─── format_detalle ────────────────────────────────────────────────────────


def test_registro_detalle_exactamente_254_chars():
    linea = format_detalle(_detalle(), FormatoImporte.A_IMPLICITO)
    assert len(linea) == LONGITUD_REGISTRO


def test_detalle_tipreg_9_en_pos_15():
    linea = format_detalle(_detalle(), FormatoImporte.A_IMPLICITO)
    assert linea[14] == '9'


def test_detalle_orden_u_en_pos_69():
    linea = format_detalle(
        _detalle(orden=OrdenDetalle.ULTIMO),
        FormatoImporte.A_IMPLICITO,
    )
    assert linea[68] == 'U'


def test_detalle_orden_m_en_pos_69():
    linea = format_detalle(
        _detalle(orden=OrdenDetalle.INTERMEDIO),
        FormatoImporte.A_IMPLICITO,
    )
    assert linea[68] == 'M'


def test_detalle_moneda_e_en_pos_253():
    linea = format_detalle(_detalle(), FormatoImporte.A_IMPLICITO)
    assert linea[252] == 'E'


def test_detalle_op_iva_s_en_pos_175():
    linea = format_detalle(_detalle(), FormatoImporte.A_IMPLICITO)
    assert linea[174] == 'S'


# ─── preview / exportar ───────────────────────────────────────────────────


def test_preview_no_escribe_fichero(tmp_path):
    lineas = preview(
        [(_cabecera(), [_detalle()])],
        FormatoImporte.A_IMPLICITO,
    )
    assert len(lineas) == 2
    assert all(len(linea) == LONGITUD_REGISTRO for linea in lineas)
    assert list(tmp_path.iterdir()) == []  # no hay ficheros creados


def test_exportar_crea_fichero_crlf(tmp_path):
    ruta = tmp_path / 'SUENLACE.DAT'
    ruta_out, sha = exportar(
        [(_cabecera(), [_detalle()])],
        ruta,
        FormatoImporte.A_IMPLICITO,
    )
    assert ruta_out == ruta
    assert ruta.exists()

    contenido_bytes = ruta.read_bytes()
    # CRLF entre líneas
    assert b'\r\n' in contenido_bytes
    # Cada línea mide 254 chars (bytes en cp1252)
    lineas = contenido_bytes.split(EOL.encode(ENCODING))
    assert all(len(linea) == LONGITUD_REGISTRO for linea in lineas)


def test_exportar_encoding_cp1252(tmp_path):
    """Confirmación empírica: el fichero se escribe en cp1252, no en UTF-8."""
    ruta = tmp_path / 'SUENLACE.DAT'
    exportar(
        [(_cabecera(descuenta='Señor Núñez'), [_detalle()])],
        ruta,
        FormatoImporte.A_IMPLICITO,
    )
    contenido = ruta.read_bytes()
    # 'ñ' en cp1252 = 0xF1; en UTF-8 sería 0xC3 0xB1
    assert b'\xf1' in contenido
    assert b'\xc3\xb1' not in contenido


def test_hash_sha256_reproducible(tmp_path):
    lista = [(_cabecera(), [_detalle()])]
    ruta1 = tmp_path / 'a.dat'
    ruta2 = tmp_path / 'b.dat'
    _, sha1 = exportar(lista, ruta1, FormatoImporte.A_IMPLICITO)
    _, sha2 = exportar(lista, ruta2, FormatoImporte.A_IMPLICITO)
    assert sha1 == sha2
    assert len(sha1) == 64  # SHA-256 hex


def test_preview_orden_cabecera_luego_detalles():
    lineas = preview(
        [(_cabecera(), [
            _detalle(orden=OrdenDetalle.INTERMEDIO),
            _detalle(orden=OrdenDetalle.ULTIMO),
        ])],
        FormatoImporte.A_IMPLICITO,
    )
    assert len(lineas) == 3
    assert lineas[0][14] == '1'  # cabecera
    assert lineas[1][14] == '9'  # detalle intermedio
    assert lineas[1][68] == 'M'
    assert lineas[2][14] == '9'  # detalle último
    assert lineas[2][68] == 'U'


def test_exportar_vacio_produce_fichero_vacio(tmp_path):
    ruta = tmp_path / 'vacio.dat'
    ruta_out, sha = exportar([], ruta, FormatoImporte.A_IMPLICITO)
    assert ruta.read_bytes() == b''
    # SHA-256 del vacío
    assert sha == 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


# ─── Alias requeridos por el plan (nombres de tests) ───────────────────────


def test_registro_exactamente_254_chars():
    """Alias de compatibilidad con el nombre listado en el plan."""
    assert len(format_cabecera(_cabecera(), FormatoImporte.A_IMPLICITO)) == 254
    assert len(format_detalle(_detalle(), FormatoImporte.A_IMPLICITO)) == 254


def test_cuenta_paddea_12_chars():
    linea = format_cabecera(_cabecera(cuenta='430001'), FormatoImporte.A_IMPLICITO)
    assert linea[15:27] == '430001      '


def test_formato_importe_a():
    """12,50€ → '00000000001250'."""
    assert format_num(Decimal('12.50'), 14, FormatoImporte.A_IMPLICITO) == '00000000001250'


def test_formato_importe_b():
    """12,50€ → '00000000012.50' (14 chars exactos)."""
    assert format_num(Decimal('12.50'), 14, FormatoImporte.B_EXPLICITO) == '00000000012.50'
