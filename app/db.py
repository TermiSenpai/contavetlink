"""Gestión del SQLite del intermediario.

- Init idempotente: crea tablas si no existen, nunca borra datos
- Versionado de esquema en la tabla `config` (clave `schema_version`)
- Migraciones automáticas al arrancar
- Conexión por request (g.db) — cerrada en teardown
- API key/value sobre la tabla `config` para que el resto de la app
  (rutas, fuentes, exporter) lea ajustes editables por el usuario
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from flask import Flask, g

from app.config import SCHEMA_VERSION, project_root

log = logging.getLogger(__name__)

# ─── Claves de la tabla `config` (single source of truth) ───────────────────
# Editables por el usuario desde la UI (/config). Cualquier código que necesite
# uno de estos valores DEBE leerlo con `get_setting()` — nunca hardcodear.

SETTING_DBF_PATH = 'dbf_path'
SETTING_EXPORTS_PATH = 'exports_path'
SETTING_CUENTA_VENTAS_DEF = 'cuenta_ventas_def'
SETTING_EJERCICIO = 'ejercicio'
SETTING_COD_EMPRESA = 'cod_empresa'
SETTING_IMPORTE_FORMATO = 'importe_formato'
SETTING_SCHEMA_VERSION = 'schema_version'
SETTING_APP_VERSION = 'app_version'

USER_EDITABLE_SETTINGS = (
    SETTING_DBF_PATH,
    SETTING_EXPORTS_PATH,
    SETTING_CUENTA_VENTAS_DEF,
    SETTING_EJERCICIO,
    SETTING_COD_EMPRESA,
    SETTING_IMPORTE_FORMATO,
)

_SETTING_DESCRIPTIONS = {
    SETTING_DBF_PATH: 'Ruta al directorio que contiene los DBFs de GESDAI',
    SETTING_EXPORTS_PATH: 'Directorio donde se guardan los SUENLACE.DAT generados',
    SETTING_CUENTA_VENTAS_DEF: 'Subcuenta de ventas por defecto (700XXX/755XXX) cuando un artículo no resuelve',
    SETTING_EJERCICIO: 'Año contable activo',
    SETTING_COD_EMPRESA: 'Código de empresa en a3ASESOR (1–99999)',
    SETTING_IMPORTE_FORMATO: "Formato de importes en SUENLACE: 'A' (escala implícita) o 'B' (decimal explícito)",
}

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS config (
    clave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL,
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS mappings_clientes (
    codigo_gesdai   TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    nif             TEXT,
    subcuenta_a3    TEXT,
    revisado        INTEGER NOT NULL DEFAULT 0,
    auto_matched    INTEGER NOT NULL DEFAULT 0,
    notas           TEXT,
    fecha_creacion  TEXT NOT NULL,
    fecha_revision  TEXT
);

CREATE TABLE IF NOT EXISTS mappings_articulos (
    clave_gesdai    TEXT PRIMARY KEY,
    descripcion     TEXT,
    cuenta_a3       TEXT,
    es_texto_libre  INTEGER NOT NULL DEFAULT 0,
    revisado        INTEGER NOT NULL DEFAULT 0,
    notas           TEXT,
    fecha_creacion  TEXT NOT NULL,
    fecha_revision  TEXT
);

CREATE TABLE IF NOT EXISTS keywords_articulos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT NOT NULL UNIQUE,
    cuenta_a3   TEXT NOT NULL,
    prioridad   INTEGER NOT NULL DEFAULT 10,
    activo      INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS exportaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_export    TEXT NOT NULL,
    fecha_desde     TEXT NOT NULL,
    fecha_hasta     TEXT NOT NULL,
    filtros_json    TEXT,
    num_facturas    INTEGER NOT NULL,
    dat_fichero     TEXT NOT NULL,
    dat_hash        TEXT NOT NULL,
    app_version     TEXT NOT NULL,
    validado        INTEGER NOT NULL DEFAULT 0,
    notas           TEXT
);

CREATE TABLE IF NOT EXISTS exportaciones_detalle (
    exportacion_id  INTEGER NOT NULL REFERENCES exportaciones(id),
    codigo_factura  TEXT NOT NULL,
    fuente          TEXT NOT NULL DEFAULT 'gesdai_dbf',
    cliente_gesdai  TEXT NOT NULL,
    subcuenta_a3    TEXT NOT NULL,
    total_coniva    REAL NOT NULL,
    resolucion_tipo TEXT NOT NULL,
    PRIMARY KEY (exportacion_id, codigo_factura)
);

CREATE INDEX IF NOT EXISTS idx_mappings_clientes_revisado
    ON mappings_clientes(revisado);
CREATE INDEX IF NOT EXISTS idx_mappings_articulos_revisado
    ON mappings_articulos(revisado);
CREATE INDEX IF NOT EXISTS idx_exportaciones_fecha
    ON exportaciones(fecha_export);
"""


def init_db(app: Flask) -> None:
    db_path: Path = app.config['DB_PATH']
    if str(db_path) != ':memory:':
        db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        _ensure_schema_version(conn)
        _run_migrations(conn)
        seed_default_settings(conn, env=app.config.get('ENV', 'development'))
        conn.commit()
    finally:
        conn.close()

    app.teardown_appcontext(_close_db)
    log.info("SQLite inicializado en %s", db_path)


# ─── API key/value sobre la tabla `config` ─────────────────────────────────


def get_setting(conn: sqlite3.Connection, clave: str) -> str | None:
    """Devuelve el valor de un ajuste o `None` si no está definido."""
    row = conn.execute(
        "SELECT valor FROM config WHERE clave = ?", (clave,)
    ).fetchone()
    if row is None:
        return None
    return row[0] if not isinstance(row, sqlite3.Row) else row['valor']


def set_setting(
    conn: sqlite3.Connection,
    clave: str,
    valor: str,
    descripcion: str | None = None,
) -> None:
    """Inserta o actualiza un ajuste. No commitea — el caller decide."""
    desc = descripcion or _SETTING_DESCRIPTIONS.get(clave)
    conn.execute(
        """
        INSERT INTO config (clave, valor, descripcion)
        VALUES (?, ?, ?)
        ON CONFLICT(clave) DO UPDATE SET
            valor = excluded.valor,
            descripcion = COALESCE(config.descripcion, excluded.descripcion)
        """,
        (clave, valor, desc),
    )


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    """Devuelve todos los ajustes editables como dict clave→valor."""
    placeholders = ','.join('?' * len(USER_EDITABLE_SETTINGS))
    rows = conn.execute(
        f"SELECT clave, valor FROM config WHERE clave IN ({placeholders})",
        USER_EDITABLE_SETTINGS,
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def seed_default_settings(conn: sqlite3.Connection, env: str) -> None:
    """Inserta ajustes por defecto si aún no existen.

    Las claves que ya tienen valor NUNCA se sobreescriben — esta función es
    100% idempotente y respeta cualquier configuración del usuario.

    En desarrollo, si el proyecto contiene una carpeta `DATA_DEV/` en la raíz,
    se usa como `dbf_path` por defecto para que arrancar de cero "just works".
    En producción no se siembra nada — el usuario configura desde la UI.
    """
    existing = {
        row[0] for row in conn.execute("SELECT clave FROM config").fetchall()
    }

    if SETTING_DBF_PATH not in existing and env == 'development':
        dev_dbf = project_root() / 'DATA_DEV'
        if dev_dbf.is_dir():
            set_setting(conn, SETTING_DBF_PATH, str(dev_dbf))
            log.info("Seed dev: dbf_path → %s", dev_dbf)


def get_db() -> sqlite3.Connection:
    if 'db' not in g:
        from flask import current_app
        conn = sqlite3.connect(str(current_app.config['DB_PATH']))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def _close_db(_exc) -> None:
    conn = g.pop('db', None)
    if conn is not None:
        conn.close()


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT valor FROM config WHERE clave = 'schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO config (clave, valor, descripcion) VALUES (?, ?, ?)",
            ('schema_version', str(SCHEMA_VERSION), 'Versión del esquema SQLite'),
        )


def _run_migrations(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT valor FROM config WHERE clave = 'schema_version'"
    ).fetchone()
    current = int(row[0]) if row else 0
    if current < SCHEMA_VERSION:
        log.info("Migrando esquema %d → %d", current, SCHEMA_VERSION)
        # Aquí irán las migraciones por versión cuando aparezcan.
        conn.execute(
            "UPDATE config SET valor = ? WHERE clave = 'schema_version'",
            (str(SCHEMA_VERSION),),
        )
