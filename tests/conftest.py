"""Fixtures comunes a toda la suite.

Las fixtures que requieren DBFs reales viven en `tests/integration/conftest.py`.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

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
    """App Flask en modo testing con SQLite en fichero tmp aislado por test.

    No usamos `:memory:` porque cada `sqlite3.connect()` crea una base
    independiente en memoria — `init_db` y los handlers de request acabarían
    viendo esquemas distintos. La fixture autouse redirige `APP_DATA_DIR` a
    un `tmp_path` por test, así que el fichero queda totalmente aislado.
    """
    from app import create_app
    from app.config import get_config

    flask_app = create_app(get_config('testing'))
    flask_app.config['TESTING'] = True
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def data_dev_dir() -> Path:
    """Devuelve la ruta al DATA_DEV local. Si no existe, skip del test.

    Busca en orden:
      1. <project_root>/DATA_DEV   (carpeta principal usada en dev)
      2. <repo>/tests/data/DATA_DEV  (alternativa para datos sintéticos)
    """
    project_root = Path(__file__).resolve().parent.parent
    candidates = [
        project_root / 'DATA_DEV',
        project_root / 'tests' / 'data' / 'DATA_DEV',
    ]
    for path in candidates:
        if path.is_dir() and any(path.iterdir()):
            return path
    pytest.skip(
        "DATA_DEV/ no encontrado — coloca DBFs en ./DATA_DEV o "
        "genera sintéticos con scripts/generate_dev_data.py"
    )
