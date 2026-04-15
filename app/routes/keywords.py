"""Panel de keywords (/keywords).

CRUD de keywords + campo "Probar" para verificar qué keyword matchea un texto.
"""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint('keywords', __name__, url_prefix='/keywords')


@bp.get('/')
def index():
    return render_template('keywords.html')


@bp.post('/')
def create():
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/<int:keyword_id>')
def update(keyword_id: int):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/<int:keyword_id>/eliminar')
def delete(keyword_id: int):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/probar')
def probar():
    """Recibe un texto y devuelve qué keyword (si alguna) matchea."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")
