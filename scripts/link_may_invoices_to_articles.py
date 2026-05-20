"""Vincula algunas lineas de las facturas de mayo a articulos existentes.

Mantiene el mix descripcion-libre + articulo para ejercitar las distintas
ramas del resolver (mapping / keyword / default) y del semaforo en dev.

Plan de vinculacion:
  FAC0000044 L1 -> ''          (descripcion libre, default)
  FAC0000045 L1 -> 'CHIP'
  FAC0000045 L2 -> 'PASAPORTE'
  FAC0000046 L1 -> 'CERT-SALUD'
  FAC0000046 L2 -> ''          (descripcion libre, default — caso mixto)
  FAC0000047 L1 -> 'RTO-TOROS'
  FAC0000048 L1 -> ''          (descripcion libre, default)

Solo modifica el campo ARTICULO de las lineas listadas. No recalcula
totales — el cuadre seguira siendo valido. Solo toca DATA_DEV.

Uso:
    python scripts/link_may_invoices_to_articles.py [--data DATA_DEV]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import dbf as d


VINCULOS: dict[tuple[str, int], str] = {
    ('FAC0000045', 1): 'CHIP',
    ('FAC0000045', 2): 'PASAPORTE',
    ('FAC0000046', 1): 'CERT-SALUD',
    ('FAC0000047', 1): 'RTO-TOROS',
    # Las demas lineas (44 L1, 46 L2, 48 L1) se quedan con ARTICULO=''
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--data',
        type=Path,
        default=Path(__file__).resolve().parent.parent / 'DATA_DEV',
    )
    args = parser.parse_args()

    lf_path = args.data / 'lfactura.dbf'
    mat_path = args.data / 'material.dbf'
    if not lf_path.is_file() or not mat_path.is_file():
        print(f"Faltan DBFs en {args.data}", file=sys.stderr)
        return 1

    # Verificar que los articulos referenciados existan en material.dbf
    mat = d.Table(str(mat_path), codepage='cp1252')
    mat.open(mode=d.READ_ONLY)
    try:
        catalogo = {str(r['CLAVEMATE']).strip() for r in mat}
    finally:
        mat.close()

    referenciados = set(VINCULOS.values())
    faltan = referenciados - catalogo
    if faltan:
        print(f"Articulos no presentes en material.dbf: {sorted(faltan)}", file=sys.stderr)
        return 2

    lf = d.Table(str(lf_path), codepage='cp1252')
    lf.open(mode=d.READ_WRITE)
    actualizadas = 0
    try:
        for r in lf:
            cod = str(r['CODIGO']).strip()
            linea = int(r['LINEA'] or 0)
            nuevo = VINCULOS.get((cod, linea))
            if nuevo is None:
                continue
            with r:
                r['ARTICULO'] = nuevo
            actualizadas += 1
            print(f"  {cod}  L{linea}  ARTICULO -> {nuevo}")
    finally:
        lf.close()

    print(f"\n{actualizadas} linea(s) vinculada(s).")

    # Resumen final del estado de las facturas de mayo
    lf = d.Table(str(lf_path), codepage='cp1252')
    lf.open(mode=d.READ_ONLY)
    try:
        print("\nEstado final FAC0000044-48:")
        for r in lf:
            cod = str(r['CODIGO']).strip()
            if 'FAC0000044' <= cod <= 'FAC0000048':
                art = str(r['ARTICULO']).strip()
                com = str(r['COMENTARIO']).strip()
                tag = art if art else '<libre>'
                print(f"  {cod} L{int(r['LINEA'] or 0)}  ART={tag:15s}  COM={com!r}")
    finally:
        lf.close()

    return 0


if __name__ == '__main__':
    sys.exit(main())
