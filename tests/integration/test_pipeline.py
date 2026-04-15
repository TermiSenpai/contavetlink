"""Test de integración Fase 3 — pipeline completo DBF → DAT.

Requiere `DATA_DEV/` en la raíz del proyecto. No corre en CI — solo en local
(la fixture `data_dev_dir` hace skip automático si no encuentra los DBFs).
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal

import pytest

from app.db import SCHEMA_SQL
from app.exporter.builder import Builder, CuadreError
from app.exporter.suenlace import (
    ENCODING,
    EOL,
    LONGITUD_REGISTRO,
    FormatoImporte,
    exportar,
)
from app.mapping.resolver import ClienteSinSubcuentaError, Resolver
from app.mapping.store import (
    marcar_cliente_revisado,
    set_subcuenta_cliente,
)
from app.mapping.sync import sync_articulos, sync_clientes
from app.sources.base import Filtros
from app.sources.dbf_source import DbfSource

pytestmark = pytest.mark.integration

# El dev data usa bases enteras (sin decimales) y TOTCONIVA también redondeado
# al entero. Eso produce diffs de cuadre de hasta ~0,50€ por factura — dentro
# de lo razonable para dev pero fuera de la tolerancia de producción (0,02€).
# Usamos 1€ aquí para ejercitar TODO el dataset sin enmascarar bugs reales;
# en producción con decimales reales se usa el default del builder (0,02€).
TOLERANCIA_DEV = Decimal('1.00')


def _nuevo_intermediario() -> sqlite3.Connection:
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    return conn


def _asignar_subcuentas_a_todos(conn: sqlite3.Connection) -> None:
    """Asigna una subcuenta 430XXX incremental a cada cliente sincronizado,
    los marca como revisados y los deja listos para exportar."""
    filas = conn.execute(
        "SELECT codigo_gesdai FROM mappings_clientes ORDER BY codigo_gesdai"
    ).fetchall()
    for idx, fila in enumerate(filas, start=1):
        subcuenta = f"430{idx:03d}"
        set_subcuenta_cliente(conn, fila['codigo_gesdai'], subcuenta)
        marcar_cliente_revisado(conn, fila['codigo_gesdai'])


def test_flujo_completo_dbf_a_dat(data_dev_dir, tmp_path):
    """DBF real → sincroniza mappings → asigna subcuentas → resuelve y
    construye registros → exporta a DAT → valida estructura del fichero."""
    # 1. Setup: intermediario + DBFs
    conn = _nuevo_intermediario()
    source = DbfSource(data_dev_dir)

    # 2. Sincronizar catálogos desde GESDAI
    r_clientes = sync_clientes(conn, source)
    r_articulos = sync_articulos(conn, source)
    assert r_clientes.insertados > 0
    assert r_articulos.insertados > 0

    # 3. Asignar subcuentas a todos los clientes (simulamos revisión manual)
    _asignar_subcuentas_a_todos(conn)

    # 4. Construir resolver + builder con tolerancia relajada para dev data
    resolver = Resolver(conn, cuenta_default='700001')
    builder = Builder(
        conn,
        resolver=resolver,
        cod_empresa=42,
        cuenta_ventas_def='700001',
        cuadre_tolerancia=TOLERANCIA_DEV,
    )

    # 5. Recorrer todas las facturas: el test debe ejercitar el dataset
    # completo, no sólo las que casualmente cuadran con tolerancia estricta.
    facturas = source.get_facturas(Filtros())
    assert len(facturas) > 0

    exportables: list[tuple] = []
    cuadre_errors: list[str] = []
    for f in facturas:
        try:
            resultado = builder.construir_registros(f)
        except CuadreError as e:
            cuadre_errors.append(str(e))
            continue
        except ClienteSinSubcuentaError:
            pytest.fail(f"Cliente {f.cliente_codigo} quedó sin subcuenta tras seed")
        exportables.append((resultado.cabecera, resultado.detalles))

    # Con tolerancia 1€ esperamos que CASI TODO el dataset pase. Si más del
    # 10% falla, probablemente hay un bug en la fórmula de cuadre, no un
    # problema de dev data.
    ratio_fallo = len(cuadre_errors) / len(facturas)
    assert ratio_fallo < 0.10, (
        f"{len(cuadre_errors)}/{len(facturas)} facturas fallan cuadre incluso "
        f"con tolerancia {TOLERANCIA_DEV}€ — revisar fórmula en "
        f"Builder._validar_cuadre.\nPrimer error: {cuadre_errors[0] if cuadre_errors else ''}"
    )
    assert len(exportables) >= 100, (
        f"Dataset dev tiene {len(facturas)} facturas pero solo {len(exportables)} "
        f"son exportables — el test no está ejercitando el pipeline seriamente"
    )

    # 6. Exportar DAT
    ruta = tmp_path / 'SUENLACE.DAT'
    ruta_out, sha = exportar(exportables, ruta, FormatoImporte.A_IMPLICITO)

    assert ruta_out.exists()
    assert len(sha) == 64

    # 7. Validación estructural del fichero
    contenido = ruta_out.read_bytes()
    lineas = contenido.split(EOL.encode(ENCODING))
    # Todas las líneas 254 chars
    for i, linea in enumerate(lineas):
        assert len(linea) == LONGITUD_REGISTRO, (
            f"línea {i+1} mide {len(linea)} bytes, esperado {LONGITUD_REGISTRO}"
        )
    # Cada factura aporta al menos 2 líneas (cabecera + 1 detalle mínimo)
    assert len(lineas) >= 2 * len(exportables)
    # Todas las cabeceras tienen tipreg='1' y los detalles '9'
    for linea in lineas:
        assert chr(linea[14]) in ('1', '9')

    # 8. SHA reproducible — re-generar el mismo DAT da el mismo hash
    ruta2 = tmp_path / 'SUENLACE_repetido.DAT'
    _, sha2 = exportar(exportables, ruta2, FormatoImporte.A_IMPLICITO)
    assert sha == sha2
