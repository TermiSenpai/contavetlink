"""Configuración de logging por entorno.

- development: texto plano legible, nivel DEBUG, consola.
- production: JSON estructurado, nivel INFO, consola + RotatingFileHandler.
- testing: nivel WARNING, consola.

El formato JSON preserva campos extra pasados vía `logger.info(..., extra={...})`,
lo que cubre el requisito de logs con contexto (`action`, `factura`, etc.).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path

from app.config import Config

# Campos internos de LogRecord que NO queremos incluir en la salida JSON.
_LOG_RECORD_INTERNAL = frozenset({
    'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
    'funcName', 'levelname', 'levelno', 'lineno', 'message', 'module',
    'msecs', 'msg', 'name', 'pathname', 'process', 'processName',
    'relativeCreated', 'stack_info', 'thread', 'threadName', 'taskName',
})


class JsonFormatter(logging.Formatter):
    """Formatter JSON estructurado.

    Emite una línea por log con: timestamp, level, logger, message, y cualquier
    campo extra pasado vía `logger.info(msg, extra={...})`.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            'timestamp': self.formatTime(record, self.datefmt),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith('_') or key in _LOG_RECORD_INTERNAL:
                continue
            payload[key] = value
        if record.exc_info:
            payload['exception'] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(config: type[Config]) -> None:
    """Configura el logger raíz según el entorno de `config`.

    Idempotente: limpia handlers previos antes de añadir los nuevos, para que
    llamarlo más de una vez (tests, reloader) no duplique salida.
    """
    root = logging.getLogger()
    root.setLevel(config.LOG_LEVEL)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setLevel(config.LOG_LEVEL)
    if config.LOG_JSON:
        console.setFormatter(JsonFormatter(datefmt='%Y-%m-%dT%H:%M:%S%z'))
    else:
        console.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        ))
    root.addHandler(console)

    if config.LOG_TO_FILE:
        logs_dir: Path = config.LOGS_DIR
        file_handler = logging.handlers.RotatingFileHandler(
            logs_dir / 'gesdai_exporter.log',
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding='utf-8',
        )
        file_handler.setLevel(config.LOG_LEVEL)
        file_handler.setFormatter(JsonFormatter(datefmt='%Y-%m-%dT%H:%M:%S%z'))
        root.addHandler(file_handler)

    # Silenciar ruido de librerías en producción.
    if config.ENV == 'production':
        logging.getLogger('werkzeug').setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging configurado",
        extra={
            'action': 'logging_configured',
            'env': config.ENV,
            'level': config.LOG_LEVEL,
            'file': config.LOG_TO_FILE,
            'json': config.LOG_JSON,
        },
    )
