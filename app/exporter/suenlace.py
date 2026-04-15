"""Formateo y escritura del fichero SUENLACE.DAT.

Especificación oficial en Sección 7 del plan:
  - Registros de longitud fija EXACTA: 254 caracteres
  - Fin de línea: CRLF (\\r\\n)
  - Encoding: cp1252 (Windows-1252)
  - tipreg en posición 15: '1' = Cabecera IVA, '9' = Detalle IVA

Formato de importes controlado por config.importe_formato:
  A — escala implícita (12,50€ → '00000000001250', entero × 100)
  B — decimal explícito (12,50€ → '00000000012.50', con punto decimal)

Los formatters NUNCA asumen que los strings ya vienen padeados — siempre
aplican su propio truncado/padding al ancho exigido por el spec. Los
caracteres que no se pueden representar en cp1252 se sustituyen por '?'
para que el fichero sea siempre escribible sin errores de encoding.
"""
from __future__ import annotations

import hashlib
import logging
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from pathlib import Path

from app.exporter.builder import (
    OrdenCabecera,
    OrdenDetalle,
    RegistroCabecera,
    RegistroDetalle,
    TipoRegistro,
)

log = logging.getLogger(__name__)

LONGITUD_REGISTRO = 254
ENCODING = 'cp1252'
EOL = '\r\n'


class FormatoImporte(str, Enum):
    A_IMPLICITO = 'A'   # ×100 implícito
    B_EXPLICITO = 'B'   # decimal explícito


# ─── Formatters básicos ────────────────────────────────────────────────────


def format_num(valor: Decimal, longitud: int, formato: FormatoImporte) -> str:
    """Formatea un importe según el formato configurado.

    Formato A: entero (valor × 100), zero-padded a la izquierda.
    Formato B: decimal con 2 cifras decimales, zero-padded a la izquierda.

    Lanza ValueError si el valor no cabe en `longitud` caracteres.
    """
    if formato == FormatoImporte.A_IMPLICITO:
        escalado = (valor * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        literal = str(int(escalado))
        if literal.startswith('-'):
            resultado = '-' + literal[1:].zfill(longitud - 1)
        else:
            resultado = literal.zfill(longitud)
    elif formato == FormatoImporte.B_EXPLICITO:
        cuantizado = valor.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        resultado = f"{cuantizado:0{longitud}.2f}"
    else:
        raise ValueError(f"Formato desconocido: {formato!r}")

    if len(resultado) != longitud:
        raise ValueError(
            f"Valor {valor!r} no cabe en campo de {longitud} chars "
            f"(formato {formato.value}): produjo {resultado!r}"
        )
    return resultado


def format_alfa(
    valor: str | None,
    longitud: int,
    *,
    justificar: str = 'izquierda',
) -> str:
    """Trunca o padea un string alfanumérico al ancho exacto.

    - Los caracteres no representables en cp1252 se sustituyen por '?'.
    - Justificación 'izquierda' → padding con espacios a la derecha (el
      caso habitual en SUENLACE).
    - Longitud resultante EXACTA: `longitud` caracteres.
    """
    if valor is None:
        valor = ''
    sanitizado = valor.encode(ENCODING, errors='replace').decode(ENCODING)
    if len(sanitizado) >= longitud:
        return sanitizado[:longitud]
    if justificar == 'izquierda':
        return sanitizado.ljust(longitud)
    if justificar == 'derecha':
        return sanitizado.rjust(longitud)
    raise ValueError(f"Justificación desconocida: {justificar!r}")


# ─── Cabecera y detalle ───────────────────────────────────────────────────


def format_cabecera(reg: RegistroCabecera, formato: FormatoImporte) -> str:
    """Serializa una cabecera IVA a una línea de exactamente 254 chars.

    Layout (ver Sección 7.3 del plan):
      pos 1  len 1   tipform   '3'
      pos 2  len 5   codemp    5 dígitos zero-padded
      pos 7  len 8   fechafac  AAAAMMDD
      pos 15 len 1   tipreg    '1' (cabecera)
      pos 16 len 12  cuenta    subcuenta cliente, espacios a la derecha
      pos 28 len 30  descuenta nombre cliente, espacios a la derecha
      pos 58 len 1   tipfac    '1' (Ventas)
      pos 59 len 10  numfac    serie+numero, espacios a la derecha
      pos 69 len 1   orden     'I' (constante cabecera)
      pos 70 len 30  desfac    descripción apunte, espacios a la derecha
      pos 100 len 14 importe   TOTCONIVA, según formato A/B
      pos 114 len 139 reserva  espacios
      pos 253 len 1  moneda    'E' (euros)
      pos 254 len 1  ind-gen   espacio
    """
    partes = [
        '3',                                              # 1   tipform
        str(reg.cod_empresa).zfill(5),                    # 2   codemp
        reg.fecha,                                        # 7   fechafac (AAAAMMDD)
        reg.tipreg.value,                                 # 15  tipreg
        format_alfa(reg.cuenta, 12),                      # 16  cuenta
        format_alfa(reg.descuenta, 30),                   # 28  descuenta
        '1',                                              # 58  tipfac (Ventas)
        format_alfa(reg.numfac, 10),                      # 59  numfac
        reg.orden.value,                                  # 69  orden
        format_alfa(reg.desfac, 30),                      # 70  desfac
        format_num(reg.importe, 14, formato),             # 100 importe
        ' ' * 139,                                        # 114 reserva
        'E',                                              # 253 moneda
        ' ',                                              # 254 ind-gen
    ]
    linea = ''.join(partes)
    _verificar_longitud(linea, reg)
    return linea


def format_detalle(reg: RegistroDetalle, formato: FormatoImporte) -> str:
    """Serializa un detalle IVA a una línea de exactamente 254 chars.

    Layout (ver Sección 7.4 del plan):
      pos 1   len 1   tipform  '3'
      pos 2   len 5   codemp   5 dígitos
      pos 7   len 8   fechafac AAAAMMDD
      pos 15  len 1   tipreg   '9'
      pos 16  len 12  cuenta   subcuenta ingreso, espacios a la derecha
      pos 28  len 30  descuenta descripción cuenta, espacios a la derecha
      pos 58  len 1   tipimp   'C' (cargo/venta)
      pos 59  len 10  numfac   igual que cabecera
      pos 69  len 1   orden    'M' intermedio / 'U' último
      pos 70  len 30  descrip  descripción, espacios a la derecha
      pos 100 len 2   subtipo  '01' (estándar)
      pos 102 len 14  base     PTSBASEn
      pos 116 len 5   por-iva  IVAn (tipo %)
      pos 121 len 14  cuo-iva  base × por-iva / 100
      pos 135 len 5   por-rec  RECEQUIn
      pos 140 len 14  cuo-rec  base × por-rec / 100
      pos 154 len 5   por-ret  RETIRPF
      pos 159 len 14  cuo-ret  base × por-ret / 100
      pos 173 len 2   impreso  '00'
      pos 175 len 1   op-iva   'S'
      pos 176 len 77  reserva  espacios
      pos 253 len 1   moneda   'E'
      pos 254 len 1   ind-gen  espacio
    """
    partes = [
        '3',                                              # 1   tipform
        str(reg.cod_empresa).zfill(5),                    # 2   codemp
        reg.fecha,                                        # 7   fechafac
        reg.tipreg.value,                                 # 15  tipreg
        format_alfa(reg.cuenta, 12),                      # 16  cuenta
        format_alfa(reg.descuenta, 30),                   # 28  descuenta
        'C',                                              # 58  tipimp (cargo)
        format_alfa(reg.numfac, 10),                      # 59  numfac
        reg.orden.value,                                  # 69  orden
        format_alfa(reg.descrip, 30),                     # 70  descrip
        '01',                                             # 100 subtipo
        format_num(reg.base, 14, formato),                # 102 base
        format_num(reg.por_iva, 5, formato),              # 116 por-iva
        format_num(reg.cuo_iva, 14, formato),             # 121 cuo-iva
        format_num(reg.por_rec, 5, formato),              # 135 por-rec
        format_num(reg.cuo_rec, 14, formato),             # 140 cuo-rec
        format_num(reg.por_ret, 5, formato),              # 154 por-ret
        format_num(reg.cuo_ret, 14, formato),             # 159 cuo-ret
        '00',                                             # 173 impreso
        'S',                                              # 175 op-iva
        ' ' * 77,                                         # 176 reserva
        'E',                                              # 253 moneda
        ' ',                                              # 254 ind-gen
    ]
    linea = ''.join(partes)
    _verificar_longitud(linea, reg)
    return linea


def _verificar_longitud(linea: str, reg: object) -> None:
    """Defensa en profundidad: el assert del builder NO es suficiente — si un
    campo se formatea mal y excede su ancho, la línea entera se descuadra y
    a3ASESOR rechaza el fichero. Fallar aquí es mejor que generar un DAT
    corrupto."""
    if len(linea) != LONGITUD_REGISTRO:
        raise ValueError(
            f"Línea SUENLACE con longitud {len(linea)} (esperado {LONGITUD_REGISTRO}): "
            f"registro {type(reg).__name__}"
        )


# ─── Preview y exportación a fichero ──────────────────────────────────────


def preview(
    cabeceras_y_detalles: list[tuple[RegistroCabecera, list[RegistroDetalle]]],
    formato: FormatoImporte,
) -> list[str]:
    """Genera las líneas en memoria sin escribir a disco.

    Orden por factura: cabecera primero, luego sus detalles. Las líneas
    entre facturas van consecutivas (no se intercalan).
    """
    lineas: list[str] = []
    for cab, detalles in cabeceras_y_detalles:
        lineas.append(format_cabecera(cab, formato))
        for det in detalles:
            lineas.append(format_detalle(det, formato))
    return lineas


def exportar(
    cabeceras_y_detalles: list[tuple[RegistroCabecera, list[RegistroDetalle]]],
    ruta_destino: Path,
    formato: FormatoImporte,
) -> tuple[Path, str]:
    """Escribe el DAT y devuelve (ruta, sha256_hex).

    El fichero queda en cp1252 con CRLF entre líneas. SIN CRLF final — se
    une con `EOL.join()`, no se añade separador colgante.

    El SHA-256 se calcula sobre los bytes finales para trazabilidad en la
    tabla `exportaciones` (Sección 6.2 del plan).
    """
    lineas = preview(cabeceras_y_detalles, formato)
    contenido = EOL.join(lineas)
    bytes_dat = contenido.encode(ENCODING)

    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
    ruta_destino.write_bytes(bytes_dat)

    sha = hashlib.sha256(bytes_dat).hexdigest()
    log.info(
        "DAT escrito: %s (%d registros, %d bytes)",
        ruta_destino, len(lineas), len(bytes_dat),
        extra={
            'action': 'dat_write',
            'ruta': str(ruta_destino),
            'registros': len(lineas),
            'sha256': sha,
        },
    )
    return ruta_destino, sha


def _hash_sha256(ruta: Path) -> str:
    """Hash SHA-256 en streaming, por si necesitamos re-verificar un DAT ya escrito."""
    h = hashlib.sha256()
    with ruta.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    'ENCODING', 'EOL', 'LONGITUD_REGISTRO',
    'FormatoImporte',
    'format_alfa', 'format_num',
    'format_cabecera', 'format_detalle',
    'preview', 'exportar',
    'OrdenCabecera', 'OrdenDetalle', 'TipoRegistro',
]
