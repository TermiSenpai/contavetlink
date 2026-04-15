"""Arranque en modo desarrollo con hot-reload.

Uso:
    python scripts/run_dev.py

Fuerza FLASK_ENV=development, carga .env/.env.development y lanza Flask con
debug + reloader. No arranca updater ni navegador (evita molestias durante
ediciones constantes).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault('FLASK_ENV', 'development')

from app import create_app  # noqa: E402
from app.config import get_config  # noqa: E402
from app.env import load_environment  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def main() -> int:
    load_environment(ROOT)
    cfg = get_config()
    configure_logging(cfg)

    app = create_app(cfg)
    app.run(
        host='127.0.0.1',
        port=cfg.FLASK_RUN_PORT,
        debug=True,
        use_reloader=True,
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
