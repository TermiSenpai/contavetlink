"""Entry point de escritorio para gesdai-exporter.

Flujo de arranque:
    1. Cargar .env/.env.<entorno> y detectar entorno (dev/prod)
    2. Configurar logging según entorno (plano en dev, JSON rotado en prod)
    3. Comprobar actualizaciones (silencioso si no hay red)
    4. Inicializar SQLite en %APPDATA%\\GesdaiExporter\\ o ruta configurada
    5. Lanzar Flask en hilo separado
    6. Abrir navegador apuntando a http://127.0.0.1:<puerto>
    7. (Futuro) Icono en systray con opción "Salir"
"""
from __future__ import annotations

import logging
import sys
import threading
import webbrowser
from pathlib import Path

from app.env import load_environment


def main() -> int:
    # En modo frozen (PyInstaller onedir), __file__ apunta a _internal/main.py,
    # pero los .env viven junto al .exe — usar sys.executable.parent.
    if getattr(sys, 'frozen', False):
        project_root = Path(sys.executable).resolve().parent
    else:
        project_root = Path(__file__).resolve().parent
    load_environment(project_root)

    # Imports diferidos: app.config resuelve env vars en el momento de `get_config()`,
    # pero importar tarde deja la intención más clara: primero entorno, luego app.
    from app import create_app
    from app.config import get_config
    from app.logging_config import configure_logging
    from updater.updater import check_for_updates

    cfg = get_config()
    configure_logging(cfg)
    log = logging.getLogger(__name__)

    log.info(
        "Arrancando %s v%s",
        cfg.APP_NAME, cfg.APP_VERSION,
        extra={'action': 'app_boot', 'env': cfg.ENV, 'data_dir': str(cfg.APP_DATA_DIR)},
    )

    try:
        check_for_updates()
    except Exception:
        log.exception("Comprobación de actualizaciones falló — continuando")

    app = create_app(cfg)
    port = cfg.FLASK_RUN_PORT
    url = f"http://127.0.0.1:{port}"

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host='127.0.0.1', port=port, debug=cfg.DEBUG, use_reloader=False)
    return 0


if __name__ == '__main__':
    sys.exit(main())
