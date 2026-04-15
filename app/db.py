"""Gestión del SQLite del intermediario.

- Init idempotente: crea tablas si no existen, nunca borra datos
- Versionado de esquema en la tabla `config` (clave `schema_version`)
- Migraciones automáticas al arrancar
- Conexión por request (g.db) — cerrada en teardown
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from flask import Flask, g

from app.config import SCHEMA_VERSION

log = logging.getLogger(__name__)

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
        conn.commit()
    finally:
        conn.close()

    app.teardown_appcontext(_close_db)
    log.info("SQLite inicializado en %s", db_path)


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
