"""Formateo y escritura del fichero SUENLACE.DAT.

Especificación oficial en Sección 7 del plan:
  - Registros de longitud fija EXACTA: 254 caracteres
  - Línea: CRLF (\\r\\n)
  - Encoding: cp1252 (Windows-1252)
  - tipreg en posición 15: '1' = Cabecera IVA, '9' = Detalle IVA

Formato de importes controlado por config.importe_formato:
  A — escala implícita (12,50€ → '00000000001250')
  B — decimal explícito ('000000000012.50')
"""
from __future__ import annotations

import hashlib
from decimal import Decimal
from enum import Enum
from pathlib import Path

from app.exporter.builder import RegistroCabecera, RegistroDetalle

LONGITUD_REGISTRO = 254
ENCODING = 'cp1252'
EOL = '\r\n'


class FormatoImporte(str, Enum):
    A_IMPLICITO = 'A'   # ×100 implícito
    B_EXPLICITO = 'B'   # decimal explícito


def format_num(valor: Decimal, longitud: int, formato: FormatoImporte) -> str:
    """Formatea un importe según el formato configurado."""
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def format_alfa(valor: str, longitud: int, *, justificar: str = 'izquierda') -> str:
    """Trunca/padea un string alfanumérico al ancho dado."""
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def format_cabecera(reg: RegistroCabecera, formato: FormatoImporte) -> str:
    """Serializa una cabecera IVA a una línea de exactamente 254 chars."""
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def format_detalle(reg: RegistroDetalle, formato: FormatoImporte) -> str:
    """Serializa un detalle IVA a una línea de exactamente 254 chars."""
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def preview(
    cabeceras_y_detalles: list[tuple[RegistroCabecera, list[RegistroDetalle]]],
    formato: FormatoImporte,
) -> list[str]:
    """Genera las líneas en memoria sin escribir a disco."""
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def exportar(
    cabeceras_y_detalles: list[tuple[RegistroCabecera, list[RegistroDetalle]]],
    ruta_destino: Path,
    formato: FormatoImporte,
) -> tuple[Path, str]:
    """Escribe el DAT y devuelve (ruta, sha256_hex).

    El fichero queda en cp1252 con CRLF. El SHA-256 se calcula sobre los
    bytes finales para trazabilidad en la tabla `exportaciones`.
    """
    raise NotImplementedError("Pendiente de implementar en Fase 3")


def _hash_sha256(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open('rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()
