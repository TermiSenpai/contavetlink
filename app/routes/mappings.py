"""Paneles de mappings — clientes (/mappings/clientes) y artículos (/mappings/articulos)."""
from __future__ import annotations

from flask import Blueprint, render_template

bp = Blueprint('mappings', __name__, url_prefix='/mappings')


# ─── Clientes ───────────────────────────────────────────────────────────────


@bp.get('/clientes')
def clientes_index():
    # progreso/clientes se rellenan en Fase 2 cuando exista el CRUD de mappings.
    return render_template('mappings_clientes.html', clientes=[], progreso={})


@bp.post('/clientes/<codigo>')
def clientes_update(codigo: str):
    """Actualiza la subcuenta de un cliente. Valida 430XXX con regex."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/clientes/<codigo>/revisar')
def clientes_marcar_revisado(codigo: str):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/clientes/import')
def clientes_import():
    """Acepta CSV o XLSX. No sobreescribe filas con revisado=1."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.get('/clientes/export')
def clientes_export():
    """Exporta a CSV o XLSX según query param `formato`."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


# ─── Artículos ──────────────────────────────────────────────────────────────


@bp.get('/articulos')
def articulos_index():
    return render_template('mappings_articulos.html')


@bp.post('/articulos/<clave>')
def articulos_update(clave: str):
    """Actualiza la cuenta de un artículo. Valida 700XXX o 755XXX."""
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/articulos/<clave>/revisar')
def articulos_marcar_revisado(clave: str):
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.post('/articulos/import')
def articulos_import():
    raise NotImplementedError("Pendiente de implementar en Fase 4")


@bp.get('/articulos/export')
def articulos_export():
    raise NotImplementedError("Pendiente de implementar en Fase 4")
