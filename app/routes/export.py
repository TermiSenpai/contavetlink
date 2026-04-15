"""Panel de exportación (/export).

Flujo:
  1. Usuario compone filtros AND/OR en el constructor visual
  2. POST /export/preview  → devuelve facturas con semáforo (verde/amarillo/rojo/gris)
  3. Si no hay rojos: POST /export/generar → produce DAT y registra en historial
"""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint('export', __name__, url_prefix='/export')


@bp.get('/')
def index():
    return render_template('export.html')


@bp.post('/preview')
def preview():
    """Aplica filtros y devuelve facturas con su estado de resolución."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/preview/excel')
def preview_excel():
    """Devuelve la preview actual como fichero Excel descargable."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/generar')
def generar():
    """Genera el DAT, lo registra en exportaciones y devuelve el fichero.

    Falla con 400 si la preview tiene cualquier 🔴 rojo.
    """
    raise NotImplementedError("Pendiente de implementar en Fase 4")
