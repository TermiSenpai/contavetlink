"""Inspecciona la estructura de un DBF (campos, tipos, contadores).

Útil para diagnosticar diferencias entre los DBFs de DATA_DEV y los reales
de COLVET, o cuando GESDAI introduce un cambio de esquema.

Uso:
    python scripts/check_dbf_structure.py path/to/cfactura.dbf
    python scripts/check_dbf_structure.py path/to/DATA/  --tabla cfactura

Abre el DBF en READ_ONLY (igual que dbf_source.py).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def inspeccionar(ruta: Path) -> None:
    """Imprime estructura y conteo de filas de un DBF."""
    raise NotImplementedError("Pendiente de implementar en Fase 0/1")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ruta', type=Path, help="Fichero DBF o directorio")
    parser.add_argument('--tabla', type=str, help="Nombre de tabla si ruta es directorio")
    args = parser.parse_args()

    if not args.ruta.exists():
        log.error("Ruta no existe: %s", args.ruta)
        return 1

    if args.ruta.is_dir():
        if not args.tabla:
            log.error("--tabla requerido cuando la ruta es un directorio")
            return 2
        inspeccionar(args.ruta / f"{args.tabla}.dbf")
    else:
        inspeccionar(args.ruta)
    return 0


if __name__ == '__main__':
    sys.exit(main())
