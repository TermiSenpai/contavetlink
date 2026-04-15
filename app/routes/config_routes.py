"""Panel de configuración (/config).

Permite al usuario configurar:
  - dbf_path           → ruta al directorio de DBFs de GESDAI
  - exports_path       → directorio donde se guardan los DAT generados
  - cuenta_ventas_def  → cuenta 700 por defecto cuando un artículo no resuelve
  - ejercicio          → año contable activo
  - cod_empresa        → código de empresa en a3ASESOR (1–99999)
  - importe_formato    → A (escala implícita) | B (decimal explícito)

Incluye botón "Verificar conexión" que abre el directorio en READ_ONLY y
comprueba que las tablas requeridas existen.

GET / cableado en Fase 1: lee los ajustes vivos de la tabla `config` del
SQLite. Los POST quedan como stub hasta Fase 4.
"""
from __future__ import annotations

from flask import Blueprint, render_template

from app.db import get_all_settings, get_db

bp = Blueprint('config', __name__, url_prefix='/config')


@bp.get('/')
def index():
    valores = get_all_settings(get_db())
    return render_template('config.html', valores=valores)


@bp.post('/')
def save():
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/verificar-dbf')
def verificar_dbf():
    """Comprueba que dbf_path contiene los DBFs requeridos."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")
