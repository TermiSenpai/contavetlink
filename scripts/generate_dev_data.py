"""Genera un set sintético de DBFs en `tests/data/DATA_DEV/`.

Crea las tablas mínimas (cfactura, lfactura, clientes, material) con datos
artificiales suficientes para que los tests de integración puedan ejercitar
el pipeline completo sin depender de los DBFs reales de COLVET.

Uso:
    python scripts/generate_dev_data.py
    python scripts/generate_dev_data.py --clientes 50 --facturas 200 --seed 42
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

DESTINO_DEFAULT = Path(__file__).resolve().parent.parent / 'tests' / 'data' / 'DATA_DEV'


def generar(destino: Path, n_clientes: int, n_facturas: int, seed: int) -> None:
    """Genera los DBFs sintéticos en `destino`.

    Estructura:
      - clientes.dbf   → n_clientes filas
      - material.dbf   → ~30 artículos
      - cfactura.dbf   → n_facturas cabeceras de factura
      - lfactura.dbf   → entre 1 y 5 líneas por factura
    """
    raise NotImplementedError("Pendiente de implementar en Fase 0/1")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destino', type=Path, default=DESTINO_DEFAULT)
    parser.add_argument('--clientes', type=int, default=20)
    parser.add_argument('--facturas', type=int, default=80)
    parser.add_argument('--seed', type=int, default=1234)
    args = parser.parse_args()

    args.destino.mkdir(parents=True, exist_ok=True)
    generar(args.destino, args.clientes, args.facturas, args.seed)
    log.info("DBFs sintéticos generados en %s", args.destino)
    return 0


if __name__ == '__main__':
    sys.exit(main())
