"""Panel de keywords (/keywords).

CRUD de keywords + campo "Probar" para verificar qué keyword matchea un texto.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from app.db import get_db
from app.mapping.keywords import add_keyword, update_keyword
from app.mapping.store import SubcuentaInvalidaError

log = logging.getLogger(__name__)
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


@bp.post('/upsert')
def upsert():
    """Crea o actualiza una keyword identificada por su texto exacto.

    Pensado para el modal de detalle de factura: al editar la cuenta de una
    línea de texto libre, el front envía aquí el comentario completo de la
    línea como `keyword` y la nueva cuenta. La asociación quedará disponible
    para futuras facturas con un comentario que contenga ese texto
    (matching substring case-insensitive).

    Si la keyword ya existe (match exacto case-sensitive), se actualiza su
    cuenta. Si no, se crea con prioridad por defecto (10) y activo=1.
    """
    data = request.get_json(silent=True) or {}
    keyword_text = (data.get('keyword') or '').strip()
    cuenta = (data.get('cuenta_a3') or '').strip()

    if not keyword_text:
        return jsonify(ok=False, error='Keyword vacía'), 400
    if not cuenta:
        return jsonify(ok=False, error='Cuenta vacía'), 400

    conn = get_db()
    existente = conn.execute(
        "SELECT id FROM keywords_articulos WHERE keyword = ?",
        (keyword_text,),
    ).fetchone()

    try:
        if existente is not None:
            update_keyword(conn, int(existente['id']), cuenta_a3=cuenta)
            keyword_id = int(existente['id'])
            accion = 'actualizada'
        else:
            keyword_id = add_keyword(
                conn,
                keyword=keyword_text,
                cuenta_a3=cuenta,
                prioridad=10,
                activo=True,
            )
            accion = 'creada'
    except SubcuentaInvalidaError as e:
        return jsonify(ok=False, error=str(e)), 400
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    conn.commit()
    log.info(
        "keyword %s: id=%s keyword=%r cuenta=%s",
        accion, keyword_id, keyword_text, cuenta,
    )
    return jsonify(
        ok=True,
        keyword_id=keyword_id,
        keyword=keyword_text,
        cuenta_a3=cuenta,
        accion=accion,
    )
