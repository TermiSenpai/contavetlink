"""Carga de variables de entorno desde ficheros .env y detección de entorno.

Orden de precedencia (mayor gana):
    1. Variables ya presentes en os.environ (shell, CI, Docker)
    2. .env.<entorno>  (e.g. .env.development, .env.production)
    3. .env  (compartido)

Las variables ya presentes en os.environ NUNCA se sobreescriben — esto permite
ejecutar con `FLASK_ENV=production python main.py` sin que un .env local las pise.

Debe llamarse ANTES de importar `app.config` para que las clases Config puedan
resolver valores desde os.environ.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def detect_environment() -> str:
    """Determina el entorno activo.

    Orden:
        1. Variable FLASK_ENV si está definida
        2. 'production' si corre como binario PyInstaller (sys.frozen)
        3. 'development' por defecto
    """
    env = os.environ.get('FLASK_ENV')
    if env:
        return env.strip().lower()
    if getattr(sys, 'frozen', False):
        return 'production'
    return 'development'


def load_dotenv(path: Path) -> int:
    """Carga variables desde un fichero .env en os.environ sin sobreescribir.

    Formato: KEY=VALUE por línea, comentarios con `#`, comillas opcionales.
    Devuelve el número de variables efectivamente aplicadas.
    Si el fichero no existe, devuelve 0 silenciosamente.
    """
    if not path.is_file():
        return 0

    try:
        content = path.read_text(encoding='utf-8')
    except OSError as e:
        log.warning("No se pudo leer %s: %s", path, e)
        return 0

    applied = 0
    for lineno, raw in enumerate(content.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            log.warning("Línea malformada en %s:%d — ignorando", path, lineno)
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if not key or key in os.environ:
            continue
        os.environ[key] = value
        applied += 1

    log.debug("Cargadas %d variables desde %s", applied, path)
    return applied


def load_environment(project_root: Path | None = None) -> str:
    """Carga los ficheros .env apropiados y devuelve el entorno activo.

    Carga primero `.env.<entorno>` y luego `.env` (el primero tiene prioridad
    porque `load_dotenv` no sobreescribe). Llamar ANTES de importar `app.config`.
    """
    root = project_root or Path.cwd()
    env = detect_environment()
    load_dotenv(root / f'.env.{env}')
    load_dotenv(root / '.env')
    os.environ.setdefault('FLASK_ENV', env)
    return env
