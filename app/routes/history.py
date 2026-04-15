"""Historial de exportaciones (/historial).

Lista de DATs generados con: fecha, rango, filtros, nº facturas, hash SHA-256.
Permite descargar DATs anteriores y marcar como validados en a3ASESOR.
"""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint('history', __name__, url_prefix='/historial')


@bp.get('/')
def index():
    return render_template('historial.html')


@bp.get('/<int:exportacion_id>/dat')
def descargar_dat(exportacion_id: int):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/<int:exportacion_id>/validar')
def marcar_validado(exportacion_id: int):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.get('/export')
def exportar_historial():
    """Exporta el historial completo a CSV o XLSX."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")
