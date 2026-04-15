"""gesdai-exporter — Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask

from app.config import Config, get_config
from app.db import init_db

log = logging.getLogger(__name__)


def create_app(config: type[Config] | None = None) -> Flask:
    cfg = config or get_config()
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(cfg)

    init_db(app)
    _register_blueprints(app)
    _register_error_handlers(app)

    log.info(
        "Flask app inicializada",
        extra={'action': 'app_init', 'env': cfg.ENV, 'version': cfg.APP_VERSION},
    )
    return app


def _register_blueprints(app: Flask) -> None:
    from flask import redirect, url_for

    from app.routes.config_routes import bp as config_bp
    from app.routes.export import bp as export_bp
    from app.routes.history import bp as history_bp
    from app.routes.keywords import bp as keywords_bp
    from app.routes.mappings import bp as mappings_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(mappings_bp)
    app.register_blueprint(keywords_bp)
    app.register_blueprint(export_bp)
    app.register_blueprint(history_bp)

    @app.get('/')
    def root():
        return redirect(url_for('export.index'))


def _register_error_handlers(app: Flask) -> None:
    from flask import render_template

    @app.errorhandler(404)
    def not_found(_e):
        return render_template('base.html', error="Página no encontrada"), 404

    @app.errorhandler(500)
    def internal_error(e):
        log.exception("Error 500: %s", e)
        return render_template('base.html', error="Error interno del servidor"), 500
