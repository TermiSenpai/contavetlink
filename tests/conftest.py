"""Fixtures comunes a toda la suite.

Las fixtures que requieren DBFs reales viven en `tests/integration/conftest.py`.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch, tmp_path):
    """Aísla cada test del entorno: forzar testing y app data en tmp."""
    monkeypatch.setenv('FLASK_ENV', 'testing')
    monkeypatch.setenv('GESDAI_APP_DATA_DIR', str(tmp_path / 'appdata'))
    monkeypatch.delenv('GESDAI_DB_PATH', raising=False)


@pytest.fixture
def db_conn() -> Iterator[sqlite3.Connection]:
    """SQLite en memoria con el esquema completo aplicado."""
    from app.db import SCHEMA_SQL

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)
    yield conn
    conn.close()


@pytest.fixture
def app():
    """App Flask en modo testing con SQLite en memoria."""
    from app import create_app
    from app.config import TestingConfig

    flask_app = create_app(TestingConfig)
    flask_app.config['TESTING'] = True
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def data_dev_dir() -> Path:
    """Devuelve la ruta al DATA_DEV local. Si no existe, skip del test."""
    path = Path(__file__).parent / 'data' / 'DATA_DEV'
    if not path.exists() or not any(path.iterdir()):
        pytest.skip("tests/data/DATA_DEV/ vacío — generar con scripts/generate_dev_data.py")
    return path
