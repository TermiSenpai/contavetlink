"""Tests de las migraciones automáticas de `_run_migrations`.

Cubre el contrato: una BD ya creada en una versión anterior debe quedar
en `SCHEMA_VERSION` sin perder datos del usuario tras `init_db`.
"""
from __future__ import annotations

import sqlite3

from app.config import SCHEMA_VERSION
from app.db import _run_migrations


def _crear_db_v1(path) -> sqlite3.Connection:
    """Reconstruye el esquema v1 (sin columna `origen`) para probar la migración."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE config (
            clave       TEXT PRIMARY KEY,
            valor       TEXT NOT NULL,
            descripcion TEXT
        );

        CREATE TABLE mappings_clientes (
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

        CREATE TABLE mappings_articulos (
            clave_gesdai    TEXT PRIMARY KEY,
            descripcion     TEXT,
            cuenta_a3       TEXT,
            es_texto_libre  INTEGER NOT NULL DEFAULT 0,
            revisado        INTEGER NOT NULL DEFAULT 0,
            notas           TEXT,
            fecha_creacion  TEXT NOT NULL,
            fecha_revision  TEXT
        );

        INSERT INTO config (clave, valor, descripcion)
            VALUES ('schema_version', '1', 'Versión del esquema SQLite');
        """
    )
    return conn


def test_migracion_v1_a_v2_anade_columna_origen(tmp_path):
    db_path = tmp_path / 'legacy.db'
    conn = _crear_db_v1(db_path)
    try:
        conn.execute(
            "INSERT INTO mappings_clientes "
            "(codigo_gesdai, nombre, fecha_creacion) "
            "VALUES ('00000001', 'CLI', '2024-01-01T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO mappings_articulos "
            "(clave_gesdai, descripcion, fecha_creacion) "
            "VALUES ('CHIP', 'Microchip', '2024-01-01T00:00:00Z')"
        )
        conn.commit()

        _run_migrations(conn)
        conn.commit()

        version = conn.execute(
            "SELECT valor FROM config WHERE clave = 'schema_version'"
        ).fetchone()[0]
        assert int(version) == SCHEMA_VERSION

        for tabla in ('mappings_clientes', 'mappings_articulos'):
            cols = {row[1] for row in conn.execute(
                f"PRAGMA table_info({tabla})"
            ).fetchall()}
            assert 'origen' in cols

        cli_origen = conn.execute(
            "SELECT origen FROM mappings_clientes WHERE codigo_gesdai = '00000001'"
        ).fetchone()[0]
        art_origen = conn.execute(
            "SELECT origen FROM mappings_articulos WHERE clave_gesdai = 'CHIP'"
        ).fetchone()[0]
        assert cli_origen == 'gesdai'
        assert art_origen == 'gesdai'
    finally:
        conn.close()


def test_migracion_idempotente(tmp_path):
    """Re-ejecutar la migración sobre una BD ya en SCHEMA_VERSION no hace nada."""
    db_path = tmp_path / 'legacy.db'
    conn = _crear_db_v1(db_path)
    try:
        _run_migrations(conn)
        conn.commit()
        # Segunda pasada: no debe romper ni perder datos
        _run_migrations(conn)
        conn.commit()
        version = conn.execute(
            "SELECT valor FROM config WHERE clave = 'schema_version'"
        ).fetchone()[0]
        assert int(version) == SCHEMA_VERSION
    finally:
        conn.close()
