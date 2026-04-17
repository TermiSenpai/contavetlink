"""Repositorio del intermediario — CRUD sobre `mappings_clientes` y `mappings_articulos`.

Es la única capa que escribe en estas tablas. Routes, sync e import/export
pasan por aquí para garantizar que:
  - las subcuentas se validan SIEMPRE con regex antes de tocar la BD
  - las filas con `revisado=1` jamás se sobreescriben silenciosamente
  - la fecha de revisión se actualiza atómicamente

Las funciones aceptan una `sqlite3.Connection` y NO commitean — el caller
decide cuándo persistir (un import masivo commitea una vez al final, un POST
de UI commitea por operación).

Contrato IMPLÍCITO: la conexión debe tener `row_factory = sqlite3.Row`. El
acceso por nombre de columna (`row['revisado']`) lo requiere. Tanto el fixture
`db_conn` de tests como `get_db()` en Flask lo configuran — si instancias una
conexión a mano para scripts, acuérdate de hacer lo mismo.

Convención para UPDATEs con flags opcionales: los parámetros `bool | None`
usan `None` como "no tocar" y se traducen a `COALESCE(?, campo_actual)` en el
SQL. Esto evita que los defaults de los callers (p.ej. `sync_articulos` que
no conoce el flag `es_texto_libre`) sobreescriban silenciosamente valores que
el operador puso a mano en la UI.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime

from app.sources.base import Articulo, Cliente

# ─── Validación de subcuentas ──────────────────────────────────────────────

# Subcuentas a3ASESOR de COLVET: 6 dígitos con prefijo fijo. Decisión D09 del
# plan — no renegociable sin hablar con el contable.
RE_SUBCUENTA_CLIENTE = re.compile(r'^430\d{3}$')
RE_SUBCUENTA_INGRESO = re.compile(r'^(700|705|755)\d{3}$')


class SubcuentaInvalidaError(ValueError):
    """La subcuenta no respeta el formato exigido por a3ASESOR."""


class CuentaDuplicadaError(ValueError):
    """Otra fila ya tiene asignada esa subcuenta.

    Las subcuentas (430XXX para clientes, 700/705/755XXX para ingresos) deben
    ser únicas dentro de su tabla — un mismo código contable no puede
    representar a dos clientes distintos ni a dos artículos distintos.
    """


def validar_subcuenta_cliente(subcuenta: str) -> str:
    """Devuelve la subcuenta si cumple `^430\\d{3}$`. Lanza si no."""
    if not isinstance(subcuenta, str) or not RE_SUBCUENTA_CLIENTE.match(subcuenta):
        raise SubcuentaInvalidaError(
            f"Subcuenta de cliente inválida: {subcuenta!r} — esperado formato 430XXX"
        )
    return subcuenta


def validar_subcuenta_ingreso(subcuenta: str) -> str:
    """Devuelve la subcuenta si cumple `^(700|705|755)\\d{3}$`. Lanza si no."""
    if not isinstance(subcuenta, str) or not RE_SUBCUENTA_INGRESO.match(subcuenta):
        raise SubcuentaInvalidaError(
            f"Subcuenta de ingreso inválida: {subcuenta!r} — "
            f"esperado 700XXX, 705XXX o 755XXX"
        )
    return subcuenta


# ─── Helpers ───────────────────────────────────────────────────────────────


def _now_iso() -> str:
    """ISO 8601 UTC con segundos — formato estable para fechas en SQLite."""
    return datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


# ─── CRUD: mappings_clientes ───────────────────────────────────────────────


def get_cliente_mapping(conn: sqlite3.Connection, codigo: str) -> dict | None:
    """Devuelve la fila completa o `None` si no existe."""
    row = conn.execute(
        "SELECT * FROM mappings_clientes WHERE codigo_gesdai = ?",
        (codigo,),
    ).fetchone()
    return _row_to_dict(row)


def list_clientes_mappings(
    conn: sqlite3.Connection,
    filtro: str = 'todos',
) -> list[dict]:
    """Lista paginable. `filtro` ∈ {'todos', 'pendientes', 'revisados'}."""
    if filtro == 'pendientes':
        sql = (
            "SELECT * FROM mappings_clientes "
            "WHERE revisado = 0 ORDER BY codigo_gesdai"
        )
    elif filtro == 'revisados':
        sql = (
            "SELECT * FROM mappings_clientes "
            "WHERE revisado = 1 ORDER BY codigo_gesdai"
        )
    elif filtro == 'todos':
        sql = "SELECT * FROM mappings_clientes ORDER BY codigo_gesdai"
    else:
        raise ValueError(f"Filtro desconocido: {filtro!r}")
    return [dict(r) for r in conn.execute(sql).fetchall()]


def progreso_clientes(conn: sqlite3.Connection) -> tuple[int, int]:
    """Devuelve `(revisados, total)` para el indicador de la UI."""
    row = conn.execute(
        "SELECT COALESCE(SUM(revisado), 0), COUNT(*) FROM mappings_clientes"
    ).fetchone()
    return int(row[0]), int(row[1])


def upsert_cliente_mapping(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    nif: str | None = None,
    subcuenta_a3: str | None = None,
    notas: str | None = None,
    revisado: bool = False,
) -> str:
    """Inserta o actualiza un mapping de cliente. Respeta `revisado=1`.

    Devuelve uno de:
      - 'insertado'  → fila nueva
      - 'actualizado' → fila existente no revisada, datos refrescados
      - 'saltado_revisado' → la fila estaba revisado=1, no se toca

    `subcuenta_a3` es opcional (puede llegar pendiente desde la sincronización
    inicial). Si llega no nula, se valida.

    `revisado` SOLO se honra en el camino INSERT (p.ej. import de un CSV
    previamente revisado). En UPDATE nunca se toca — para cambiar el estado
    de una fila existente usa `marcar_cliente_revisado()`.
    """
    if subcuenta_a3 is not None:
        validar_subcuenta_cliente(subcuenta_a3)

    existing = get_cliente_mapping(conn, codigo)
    if existing is not None and existing['revisado'] == 1:
        return 'saltado_revisado'

    if existing is None:
        ahora = _now_iso()
        conn.execute(
            """
            INSERT INTO mappings_clientes
                (codigo_gesdai, nombre, nif, subcuenta_a3, notas,
                 revisado, fecha_revision, fecha_creacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                codigo, nombre, nif, subcuenta_a3, notas,
                1 if revisado else 0,
                ahora if revisado else None,
                ahora,
            ),
        )
        return 'insertado'

    conn.execute(
        """
        UPDATE mappings_clientes
        SET nombre = ?,
            nif = ?,
            subcuenta_a3 = COALESCE(?, subcuenta_a3),
            notas = COALESCE(?, notas)
        WHERE codigo_gesdai = ?
        """,
        (nombre, nif, subcuenta_a3, notas, codigo),
    )
    return 'actualizado'


def set_subcuenta_cliente(
    conn: sqlite3.Connection,
    codigo: str,
    subcuenta_a3: str,
) -> None:
    """Cambia la subcuenta de un cliente. Lanza si no existe, es inválida o
    ya está asignada a otro cliente."""
    validar_subcuenta_cliente(subcuenta_a3)
    dup = conn.execute(
        "SELECT codigo_gesdai FROM mappings_clientes "
        "WHERE subcuenta_a3 = ? AND codigo_gesdai != ?",
        (subcuenta_a3, codigo),
    ).fetchone()
    if dup is not None:
        raise CuentaDuplicadaError(
            f"La subcuenta {subcuenta_a3} ya está asignada al cliente {dup[0]}"
        )
    cur = conn.execute(
        "UPDATE mappings_clientes SET subcuenta_a3 = ? WHERE codigo_gesdai = ?",
        (subcuenta_a3, codigo),
    )
    if cur.rowcount == 0:
        raise KeyError(f"Cliente no encontrado: {codigo}")


def marcar_cliente_revisado(
    conn: sqlite3.Connection,
    codigo: str,
    revisado: bool = True,
) -> None:
    """Marca o desmarca como revisado. Atómico con la fecha."""
    fecha = _now_iso() if revisado else None
    cur = conn.execute(
        """
        UPDATE mappings_clientes
        SET revisado = ?, fecha_revision = ?
        WHERE codigo_gesdai = ?
        """,
        (1 if revisado else 0, fecha, codigo),
    )
    if cur.rowcount == 0:
        raise KeyError(f"Cliente no encontrado: {codigo}")


# ─── CRUD: mappings_articulos ──────────────────────────────────────────────


def get_articulo_mapping(conn: sqlite3.Connection, clave: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM mappings_articulos WHERE clave_gesdai = ?",
        (clave,),
    ).fetchone()
    return _row_to_dict(row)


def list_articulos_mappings(
    conn: sqlite3.Connection,
    filtro: str = 'todos',
) -> list[dict]:
    if filtro == 'pendientes':
        sql = (
            "SELECT * FROM mappings_articulos "
            "WHERE revisado = 0 ORDER BY clave_gesdai"
        )
    elif filtro == 'revisados':
        sql = (
            "SELECT * FROM mappings_articulos "
            "WHERE revisado = 1 ORDER BY clave_gesdai"
        )
    elif filtro == 'todos':
        sql = "SELECT * FROM mappings_articulos ORDER BY clave_gesdai"
    else:
        raise ValueError(f"Filtro desconocido: {filtro!r}")
    return [dict(r) for r in conn.execute(sql).fetchall()]


def progreso_articulos(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COALESCE(SUM(revisado), 0), COUNT(*) FROM mappings_articulos"
    ).fetchone()
    return int(row[0]), int(row[1])


def upsert_articulo_mapping(
    conn: sqlite3.Connection,
    clave: str,
    descripcion: str | None = None,
    cuenta_a3: str | None = None,
    es_texto_libre: bool | None = None,
    notas: str | None = None,
    revisado: bool = False,
) -> str:
    """Inserta o actualiza un mapping de artículo. Respeta `revisado=1`.

    Si `cuenta_a3` llega no nula, se valida con la regex de ingresos. El
    pipeline de resolución (Fase 3) usa esta misma función para persistir
    matches automáticos como pendientes — por eso `cuenta_a3` es opcional.

    `es_texto_libre` usa `None` como "no tocar": en el UPDATE se aplica con
    COALESCE para que `sync_articulos` (que no conoce el flag) no pise el
    valor que el operador marcó en la UI. En el INSERT, `None` se trata
    como `False`.

    `revisado` SOLO se honra en INSERT (import de CSV previamente revisado).
    En UPDATE nunca se toca — usar `marcar_articulo_revisado()`.
    """
    if cuenta_a3 is not None:
        validar_subcuenta_ingreso(cuenta_a3)

    existing = get_articulo_mapping(conn, clave)
    if existing is not None and existing['revisado'] == 1:
        return 'saltado_revisado'

    es_texto_libre_int = (
        None if es_texto_libre is None else (1 if es_texto_libre else 0)
    )

    if existing is None:
        ahora = _now_iso()
        conn.execute(
            """
            INSERT INTO mappings_articulos
                (clave_gesdai, descripcion, cuenta_a3, es_texto_libre,
                 notas, revisado, fecha_revision, fecha_creacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clave,
                descripcion,
                cuenta_a3,
                es_texto_libre_int if es_texto_libre_int is not None else 0,
                notas,
                1 if revisado else 0,
                ahora if revisado else None,
                ahora,
            ),
        )
        return 'insertado'

    conn.execute(
        """
        UPDATE mappings_articulos
        SET descripcion = COALESCE(?, descripcion),
            cuenta_a3 = COALESCE(?, cuenta_a3),
            es_texto_libre = COALESCE(?, es_texto_libre),
            notas = COALESCE(?, notas)
        WHERE clave_gesdai = ?
        """,
        (descripcion, cuenta_a3, es_texto_libre_int, notas, clave),
    )
    return 'actualizado'


def set_cuenta_articulo(
    conn: sqlite3.Connection,
    clave: str,
    cuenta_a3: str,
) -> None:
    validar_subcuenta_ingreso(cuenta_a3)
    dup = conn.execute(
        "SELECT clave_gesdai FROM mappings_articulos "
        "WHERE cuenta_a3 = ? AND clave_gesdai != ?",
        (cuenta_a3, clave),
    ).fetchone()
    if dup is not None:
        raise CuentaDuplicadaError(
            f"La cuenta {cuenta_a3} ya está asignada al artículo {dup[0]}"
        )
    cur = conn.execute(
        "UPDATE mappings_articulos SET cuenta_a3 = ? WHERE clave_gesdai = ?",
        (cuenta_a3, clave),
    )
    if cur.rowcount == 0:
        raise KeyError(f"Artículo no encontrado: {clave}")


def marcar_articulo_revisado(
    conn: sqlite3.Connection,
    clave: str,
    revisado: bool = True,
) -> None:
    fecha = _now_iso() if revisado else None
    cur = conn.execute(
        """
        UPDATE mappings_articulos
        SET revisado = ?, fecha_revision = ?
        WHERE clave_gesdai = ?
        """,
        (1 if revisado else 0, fecha, clave),
    )
    if cur.rowcount == 0:
        raise KeyError(f"Artículo no encontrado: {clave}")


# ─── Conversores desde modelos de dominio ─────────────────────────────────


def upsert_cliente_desde_modelo(conn: sqlite3.Connection, cliente: Cliente) -> str:
    """Adapter para insertar un `Cliente` (de `sources/base.py`) sin reflejar
    aún ninguna subcuenta — el operador la asigna después."""
    return upsert_cliente_mapping(
        conn,
        codigo=cliente.codigo,
        nombre=cliente.nombre,
        nif=cliente.nif,
    )


def upsert_articulo_desde_modelo(conn: sqlite3.Connection, articulo: Articulo) -> str:
    return upsert_articulo_mapping(
        conn,
        clave=articulo.clave,
        descripcion=articulo.descripcion,
    )
