"""Recrea cfactura.dbf y lfactura.dbf de DATA_DEV con precisión decimal.

El esquema original tenía los campos monetarios como N(13,0) y N(12,0), por lo
que cualquier total con decimales se truncaba al guardar. Esto provocaba
descuadres falsos al validar cuadre de IVA en el exporter.

Este script:
  1. Lee todas las filas de cfactura.dbf y lfactura.dbf
  2. Renombra los originales a *.dbf.bak
  3. Crea los DBFs nuevos con los campos monetarios como N(13,2)/N(12,2)
  4. Re-inserta todas las filas, recalculando TOTCONIVA exacto a partir de
     PTSBASE×IVA para que cuadren con tolerancia 0,02 €

Solo se toca DATA_DEV — los DBFs reales de GESDAI siguen siendo READ-ONLY.

Uso:
    python scripts/fix_decimals_dev_data.py [--data DATA_DEV]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import dbf as d

# Campos cuyo tipo necesita pasar de N(x,0) a N(x,2) para soportar céntimos.
CFACTURA_MONEY_TO_2DEC = {
    'PTSAGENTE', 'TOTPTS', 'TOTCONIVA', 'TOTPAGADO',
    'PTSBASE1', 'PTSBASE2', 'PTSBASE3',
    'IMPORCOSTE', 'FRANQUICIA', 'TOTCIA',
}
LFACTURA_MONEY_TO_2DEC = {'PRECIOV', 'TOTLINEA', 'PRECIOC', 'PRECNETOC'}

# Mapeo numérico → letra de tipo del lenguaje de specs de la librería `dbf`.
TYPE_CODE_TO_LETTER = {67: 'C', 78: 'N', 68: 'D', 76: 'L', 77: 'M'}


def field_spec(name: str, info, force_decimals: int | None = None) -> str:
    """Construye la cadena de especificación para un campo del DBF."""
    type_code, length, decimals, _ = info
    letter = TYPE_CODE_TO_LETTER[type_code]
    if letter == 'C':
        return f'{name} C({length})'
    if letter == 'N':
        dec = force_decimals if force_decimals is not None else decimals
        return f'{name} N({length},{dec})'
    if letter == 'D':
        return f'{name} D'
    if letter == 'L':
        return f'{name} L'
    if letter == 'M':
        return f'{name} M'
    raise ValueError(f"Tipo de campo no soportado: {type_code} ({name})")


def build_spec(table: d.Table, force_2dec_fields: set[str]) -> str:
    parts = []
    for name in table.field_names:
        info = table.field_info(name)
        force = 2 if name in force_2dec_fields else None
        parts.append(field_spec(name, info, force))
    return '; '.join(parts)


def dump_rows(table: d.Table) -> list[dict]:
    fields = table.field_names
    return [{f: r[f] for f in fields} for r in table]


def recompute_totales(cab: dict, lineas_por_codigo: dict[str, list[dict]]) -> dict:
    """Devuelve la cabecera con PTSBASE/IVA/TOTCONIVA recalculados desde lineas.

    Para cada cabecera con líneas asociadas, agrupamos los importes por tipo
    de IVA en bandas 1/2/3 y recalculamos TOTCONIVA exacto. Si la cabecera no
    tiene líneas (caso poco probable en DATA_DEV), preservamos los valores
    actuales.
    """
    codigo = str(cab['CODIGO']).strip()
    lineas = lineas_por_codigo.get(codigo, [])
    if not lineas:
        return cab

    # Agrupar bases por tipo de IVA (banda 1/2/3 segun aparezca)
    bandas: dict[Decimal, Decimal] = {}
    for ln in lineas:
        cant = Decimal(str(ln['CANTIDAD'] or 0))
        prec = Decimal(str(ln['PRECIOV'] or 0))
        dto = Decimal(str(ln['DTO'] or 0))
        iva = Decimal(str(ln['IVA'] or 0))
        bruto = (cant * prec).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if dto:
            bruto = (bruto * (Decimal('1') - dto / Decimal('100'))).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP,
            )
        bandas[iva] = bandas.get(iva, Decimal('0')) + bruto

    # Asignar a PTSBASE1/2/3 + IVA1/2/3 + RECEQUI1/2/3
    bandas_ordenadas = sorted(bandas.items(), key=lambda kv: kv[0], reverse=True)[:3]
    nuevo = dict(cab)
    for i in range(1, 4):
        nuevo[f'PTSBASE{i}'] = Decimal('0')
        nuevo[f'IVA{i}'] = Decimal('0')
        nuevo[f'RECEQUI{i}'] = Decimal('0')
    for idx, (iva, base) in enumerate(bandas_ordenadas, start=1):
        nuevo[f'PTSBASE{idx}'] = base
        nuevo[f'IVA{idx}'] = iva
        # RECEQUI se preserva si ya existia para esa banda (no hay forma de
        # derivarlo desde lineas), pero en DATA_DEV es siempre 0.
        nuevo[f'RECEQUI{idx}'] = Decimal(str(cab.get(f'RECEQUI{idx}', 0) or 0))

    bases_total = sum((b for _, b in bandas_ordenadas), Decimal('0'))
    cuotas_iva = sum(
        (base * iva / Decimal('100') for iva, base in bandas_ordenadas),
        Decimal('0'),
    )
    cuotas_rec = sum(
        (Decimal(str(nuevo[f'PTSBASE{i}'])) * Decimal(str(nuevo[f'RECEQUI{i}'])) / Decimal('100')
         for i in range(1, 4)),
        Decimal('0'),
    )
    retirpf = Decimal(str(cab.get('RETIRPF', 0) or 0))
    retencion = bases_total * retirpf / Decimal('100')

    total_con_iva = (bases_total + cuotas_iva + cuotas_rec - retencion).quantize(
        Decimal('0.01'), rounding=ROUND_HALF_UP,
    )
    nuevo['TOTPTS'] = bases_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    nuevo['TOTCONIVA'] = total_con_iva
    return nuevo


def recrear_tabla(path: Path, spec: str, rows: list[dict]) -> None:
    """Renombra el original a .bak y crea uno nuevo con la spec dada."""
    bak = path.with_suffix(path.suffix + '.bak')
    if bak.exists():
        bak.unlink()
    shutil.move(str(path), str(bak))

    nueva = d.Table(str(path), spec, codepage='cp1252')
    nueva.open(mode=d.READ_WRITE)
    try:
        for r in rows:
            nueva.append(r)
    finally:
        nueva.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--data',
        type=Path,
        default=Path(__file__).resolve().parent.parent / 'DATA_DEV',
    )
    args = parser.parse_args()

    cf_path = args.data / 'cfactura.dbf'
    lf_path = args.data / 'lfactura.dbf'
    if not cf_path.is_file() or not lf_path.is_file():
        print(f"No se encontraron DBFs en {args.data}", file=sys.stderr)
        return 1

    # 1. Leer todo en memoria + construir specs nuevas
    cf = d.Table(str(cf_path), codepage='cp1252')
    cf.open(mode=d.READ_ONLY)
    try:
        cf_spec = build_spec(cf, CFACTURA_MONEY_TO_2DEC)
        cf_rows = dump_rows(cf)
    finally:
        cf.close()

    lf = d.Table(str(lf_path), codepage='cp1252')
    lf.open(mode=d.READ_ONLY)
    try:
        lf_spec = build_spec(lf, LFACTURA_MONEY_TO_2DEC)
        lf_rows = dump_rows(lf)
    finally:
        lf.close()

    # 2. Indexar lineas por codigo de factura
    lineas_por_codigo: dict[str, list[dict]] = {}
    for ln in lf_rows:
        cod = str(ln['CODIGO']).strip()
        lineas_por_codigo.setdefault(cod, []).append(ln)

    # 3. Recalcular cabeceras
    cf_rows_nuevas = [recompute_totales(c, lineas_por_codigo) for c in cf_rows]

    # 4. Recrear DBFs
    recrear_tabla(cf_path, cf_spec, cf_rows_nuevas)
    recrear_tabla(lf_path, lf_spec, lf_rows)

    print(f"OK: {len(cf_rows_nuevas)} cabeceras y {len(lf_rows)} lineas reescritas con decimales")
    print(f"     Backups: {cf_path}.bak  /  {lf_path}.bak")

    # 5. Verificacion rapida: cuadre de las 5 nuevas
    print("\nMuestra de cuadre (ultimas 5 facturas):")
    for r in cf_rows_nuevas[-5:]:
        codigo = str(r['CODIGO']).strip()
        bases = (Decimal(str(r['PTSBASE1'] or 0))
                 + Decimal(str(r['PTSBASE2'] or 0))
                 + Decimal(str(r['PTSBASE3'] or 0)))
        tot = Decimal(str(r['TOTCONIVA'] or 0))
        print(f"  {codigo}  bases={bases}  TOTCONIVA={tot}")

    return 0


if __name__ == '__main__':
    sys.exit(main())
