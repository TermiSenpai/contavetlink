"""Añade facturas de solo-descripción al DATA_DEV.

Cada línea tiene `ARTICULO` vacío y `COMENTARIO` con texto libre, para ejercitar
la resolución por keyword/default en el pipeline. Escribe solo sobre
DATA_DEV/ — los DBF reales de GESDAI siguen siendo READ-ONLY por contrato.

Uso:
    python scripts/add_description_only_invoices.py [--data DATA_DEV]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import dbf as d


NUEVAS = [
    {
        'numero': '000044',
        'cliente': 'CLI00005',
        'fecha': date(2026, 5, 2),
        'lineas': [
            {'comentario': 'Consulta general perro mestizo', 'cantidad': 1, 'precio': Decimal('35.00'), 'iva': Decimal('21')},
        ],
    },
    {
        'numero': '000045',
        'cliente': 'CLI00012',
        'fecha': date(2026, 5, 4),
        'lineas': [
            {'comentario': 'Revision pre-quirurgica gato', 'cantidad': 1, 'precio': Decimal('45.00'), 'iva': Decimal('21')},
            {'comentario': 'Analitica sangre basica', 'cantidad': 1, 'precio': Decimal('28.00'), 'iva': Decimal('21')},
        ],
    },
    {
        'numero': '000046',
        'cliente': 'CLI00020',
        'fecha': date(2026, 5, 6),
        'lineas': [
            {'comentario': 'Urgencia nocturna fin de semana', 'cantidad': 1, 'precio': Decimal('80.00'), 'iva': Decimal('21')},
            {'comentario': 'Curas y vendaje pata trasera', 'cantidad': 2, 'precio': Decimal('15.00'), 'iva': Decimal('21')},
        ],
    },
    {
        'numero': '000047',
        'cliente': 'CLI00008',
        'fecha': date(2026, 5, 9),
        'lineas': [
            {'comentario': 'Cirugia castracion gato macho', 'cantidad': 1, 'precio': Decimal('120.00'), 'iva': Decimal('21')},
        ],
    },
    {
        'numero': '000048',
        'cliente': 'CLI00030',
        'fecha': date(2026, 5, 11),
        'lineas': [
            {'comentario': 'Radiografia torax perro grande', 'cantidad': 1, 'precio': Decimal('55.00'), 'iva': Decimal('21')},
        ],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path(__file__).resolve().parent.parent / 'DATA_DEV')
    args = parser.parse_args()

    cfactura_path = args.data / 'cfactura.dbf'
    lfactura_path = args.data / 'lfactura.dbf'
    if not cfactura_path.is_file() or not lfactura_path.is_file():
        print(f"No se encontraron DBFs en {args.data}", file=sys.stderr)
        return 1

    cfactura = d.Table(str(cfactura_path), codepage='cp1252')
    cfactura.open(mode=d.READ_WRITE)
    try:
        codigos_existentes = {str(r['CODIGO']).strip() for r in cfactura}

        lfactura = d.Table(str(lfactura_path), codepage='cp1252')
        lfactura.open(mode=d.READ_WRITE)
        try:
            añadidas = 0
            for f in NUEVAS:
                codigo = f"FAC{int(f['numero']):07d}"
                if codigo in codigos_existentes:
                    print(f"  skip {codigo} (ya existe)")
                    continue

                base = sum((l['cantidad'] * l['precio'] for l in f['lineas']), Decimal('0'))
                total_iva = (base * Decimal('0.21')).quantize(Decimal('0.01'))
                total_con_iva = base + total_iva

                cfactura.append({
                    'CODIGO': codigo,
                    'SERIE': 'A',
                    'NUMERO': f['numero'],
                    'CLIENTE': f['cliente'],
                    'FECHA': f['fecha'],
                    'FPAGO': '60',
                    'TOTPTS': base,
                    'TOTCONIVA': total_con_iva,
                    'PTSBASE1': base,
                    'IVA1': Decimal('21'),
                    'RECEQUI1': Decimal('0'),
                    'PTSBASE2': Decimal('0'),
                    'IVA2': Decimal('0'),
                    'RECEQUI2': Decimal('0'),
                    'PTSBASE3': Decimal('0'),
                    'IVA3': Decimal('0'),
                    'RECEQUI3': Decimal('0'),
                    'CONTABIL': False,
                    'RETIRPF': Decimal('0'),
                })

                for idx, linea in enumerate(f['lineas'], start=1):
                    total_linea = linea['cantidad'] * linea['precio']
                    lfactura.append({
                        'CODIGO': codigo,
                        'LINEA': idx,
                        'ARTICULO': '',
                        'COMENTARIO': linea['comentario'],
                        'CANTIDAD': Decimal(str(linea['cantidad'])),
                        'PRECIOV': linea['precio'],
                        'IVA': linea['iva'],
                        'DTO': Decimal('0'),
                        'TOTLINEA': total_linea,
                    })

                añadidas += 1
                print(f"  + {codigo} · {f['cliente']} · {f['fecha']} · {len(f['lineas'])} linea(s) · {total_con_iva} €")
        finally:
            lfactura.close()
    finally:
        cfactura.close()

    print(f"\n{añadidas} factura(s) añadida(s) a {args.data}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
