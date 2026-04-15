"""Configuración de la aplicación por entorno.

La configuración estable del usuario (rutas DBF, ejercicio, cuenta ventas...)
vive en la tabla `config` del SQLite — este módulo solo cubre arranque, rutas
de datos, logging y diferencias dev/prod.

Uso normal:
    from app.env import load_environment
    from app.config import get_config
    load_environment()
    cfg = get_config()   # resuelve DevelopmentConfig / ProductionConfig / TestingConfig

Detección automática en `get_config()`:
    1. FLASK_ENV si está definido
    2. 'production' si corre como binario PyInstaller (sys.frozen)
    3. 'development' por defecto
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

APP_NAME = "GesdaiExporter"
APP_VERSION = "0.1.0"
SCHEMA_VERSION = 1


# ─── Resolución de rutas ────────────────────────────────────────────────────


def project_root() -> Path:
    """Raíz del proyecto (en desarrollo). En prod frozen sigue siendo válido
    para referenciar recursos estáticos empaquetados, pero los datos de usuario
    nunca deben vivir aquí — usa `resolve_app_data_dir()`."""
    return Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def resolve_app_data_dir(env: str) -> Path:
    """Directorio persistente de datos del usuario.

    - production: %APPDATA%\\GesdaiExporter\\  (Windows) o ~/.gesdaiexporter
    - development: <proyecto>/var/
    - testing: <proyecto>/var/test/

    Sobreescribible con GESDAI_APP_DATA_DIR (útil para CI y builds portables).
    """
    override = os.environ.get('GESDAI_APP_DATA_DIR')
    if override:
        path = Path(override)
    elif env == 'production':
        if os.name == 'nt' and 'APPDATA' in os.environ:
            path = Path(os.environ['APPDATA']) / APP_NAME
        else:
            path = Path.home() / f'.{APP_NAME.lower()}'
    elif env == 'testing':
        path = project_root() / 'var' / 'test'
    else:  # development y cualquier otro fallback
        path = project_root() / 'var'
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_db_path(env: str, app_data_dir: Path) -> Path:
    override = os.environ.get('GESDAI_DB_PATH')
    if override:
        return Path(override)
    return app_data_dir / 'gesdai_exporter.db'


def resolve_logs_dir(app_data_dir: Path) -> Path:
    path = app_data_dir / 'logs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_exports_dir(app_data_dir: Path) -> Path:
    """Directorio por defecto para los ficheros SUENLACE.DAT generados.

    Es solo el default — el usuario puede cambiarlo desde la UI (tabla `config`,
    clave `exports_path`).
    """
    override = os.environ.get('GESDAI_EXPORTS_DIR')
    if override:
        path = Path(override)
    else:
        path = app_data_dir / 'exports'
    path.mkdir(parents=True, exist_ok=True)
    return path


# ─── Clases de configuración ────────────────────────────────────────────────


class Config:
    """Base común. No instanciar directamente — usar `get_config()`."""

    ENV: str = 'base'

    APP_NAME = APP_NAME
    APP_VERSION = APP_VERSION
    SCHEMA_VERSION = SCHEMA_VERSION

    DEBUG = False
    TESTING = False

    SECRET_KEY: str = ''
    FLASK_RUN_PORT: int = 5000

    LOG_LEVEL: str = 'INFO'
    LOG_TO_FILE: bool = False
    LOG_JSON: bool = False

    JSON_AS_ASCII = False
    JSONIFY_PRETTYPRINT_REGULAR = False

    # Rellenados por `get_config()` con valores resueltos según el entorno.
    APP_DATA_DIR: Path = Path()
    DB_PATH: Path = Path()
    LOGS_DIR: Path = Path()
    EXPORTS_DIR: Path = Path()


class DevelopmentConfig(Config):
    ENV = 'development'
    DEBUG = True
    LOG_TO_FILE = False
    LOG_JSON = False
    _DEFAULT_LOG_LEVEL = 'DEBUG'
    _DEFAULT_SECRET_KEY = 'dev-only-change-in-production'


class ProductionConfig(Config):
    ENV = 'production'
    DEBUG = False
    LOG_TO_FILE = True
    LOG_JSON = True
    _DEFAULT_LOG_LEVEL = 'INFO'
    _DEFAULT_SECRET_KEY = ''  # obligatorio vía env var


class TestingConfig(Config):
    ENV = 'testing'
    TESTING = True
    DEBUG = True
    LOG_TO_FILE = False
    LOG_JSON = False
    _DEFAULT_LOG_LEVEL = 'WARNING'
    _DEFAULT_SECRET_KEY = 'testing'


_CONFIG_MAP: dict[str, type[Config]] = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
}


def _auto_env() -> str:
    if is_frozen():
        return 'production'
    return 'development'


def get_config(env: str | None = None) -> type[Config]:
    """Devuelve la clase de configuración con valores resueltos del entorno.

    Importante: mutar atributos de clase aquí (en vez de a nivel de módulo)
    garantiza que se leen las variables de entorno ya cargadas por
    `app.env.load_environment()` — sin orden de importación frágil.
    """
    resolved_env = (env or os.environ.get('FLASK_ENV') or _auto_env()).strip().lower()

    try:
        cls = _CONFIG_MAP[resolved_env]
    except KeyError as e:
        raise ValueError(
            f"FLASK_ENV desconocido: {resolved_env!r} "
            f"(válidos: {sorted(_CONFIG_MAP)})"
        ) from e

    cls.SECRET_KEY = os.environ.get('SECRET_KEY', cls._DEFAULT_SECRET_KEY)
    cls.FLASK_RUN_PORT = int(os.environ.get('FLASK_RUN_PORT', '5000'))
    cls.LOG_LEVEL = os.environ.get('LOG_LEVEL', cls._DEFAULT_LOG_LEVEL)

    cls.APP_DATA_DIR = resolve_app_data_dir(cls.ENV)
    cls.LOGS_DIR = resolve_logs_dir(cls.APP_DATA_DIR)
    cls.EXPORTS_DIR = resolve_exports_dir(cls.APP_DATA_DIR)

    if cls is TestingConfig:
        cls.DB_PATH = Path(':memory:')
    else:
        cls.DB_PATH = resolve_db_path(cls.ENV, cls.APP_DATA_DIR)

    if cls is ProductionConfig:
        _validate_production(cls)

    return cls


def _validate_production(cls: type[Config]) -> None:
    """Comprueba invariantes críticos de producción. Falla rápido si falta algo."""
    if not cls.SECRET_KEY or cls.SECRET_KEY == 'dev-only-change-in-production':
        raise RuntimeError(
            "SECRET_KEY no configurado en producción. Genera uno con:\n"
            '  python -c "import secrets; print(secrets.token_hex(32))"\n'
            "y añádelo a .env.production o como variable de entorno."
        )
