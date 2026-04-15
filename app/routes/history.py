"""Historial de exportaciones (/historial).

Lista de DATs generados con: fecha, rango, filtros, nº facturas, hash SHA-256.
Permite descargar DATs anteriores y marcar como validados en a3ASESOR.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
)

from app.db import get_db
from app.io import csv_handler, excel_handler

log = logging.getLogger(__name__)
bp = Blueprint('history', __name__, url_prefix='/historial')


@bp.get('/')
def index():
    conn = get_db()
    filas = conn.execute(
        """
        SELECT id, fecha_export, fecha_desde, fecha_hasta, filtros_json,
               num_facturas, dat_fichero, dat_hash, app_version, validado, notas
        FROM exportaciones
        ORDER BY fecha_export DESC
        """
    ).fetchall()
    exportaciones = [dict(f) for f in filas]
    return render_template('historial.html', exportaciones=exportaciones)


@bp.get('/<int:exportacion_id>/dat')
def descargar_dat(exportacion_id: int):
    """Devuelve el fichero .DAT registrado en la tabla `exportaciones`.

    Validación defensiva: la ruta puede haberse movido (el usuario borra el
    fichero, cambia `exports_path`, etc.). Si no existe, 404 con mensaje claro.
    """
    conn = get_db()
    fila = conn.execute(
        "SELECT dat_fichero FROM exportaciones WHERE id = ?",
        (exportacion_id,),
    ).fetchone()
    if fila is None:
        abort(404, f"Exportación {exportacion_id} no encontrada")

    ruta = Path(fila['dat_fichero'])
    if not ruta.is_file():
        abort(
            410,
            f"El fichero DAT original ya no está en disco: {ruta}. "
            f"Puede haberse movido o borrado.",
        )

    return send_file(
        ruta,
        mimetype='text/plain; charset=cp1252',
        as_attachment=True,
        download_name=ruta.name,
    )


@bp.post('/<int:exportacion_id>/validar')
def marcar_validado(exportacion_id: int):
    """Marca una exportación como validada en a3ASESOR.

    Acepta JSON `{validado: true/false, notas: "..."}`. Solo actualiza los
    campos que llegan no-null — así un update parcial preserva lo demás.
    """
    data = request.get_json(silent=True) or request.form
    conn = get_db()
    fila = conn.execute(
        "SELECT id FROM exportaciones WHERE id = ?",
        (exportacion_id,),
    ).fetchone()
    if fila is None:
        return jsonify(ok=False, error="Exportación no encontrada"), 404

    validado_raw = data.get('validado', True)
    validado = validado_raw if isinstance(validado_raw, bool) else str(validado_raw).lower() not in ('0', 'false', 'no')
    notas = data.get('notas')

    if notas is not None:
        conn.execute(
            "UPDATE exportaciones SET validado = ?, notas = ? WHERE id = ?",
            (1 if validado else 0, notas, exportacion_id),
        )
    else:
        conn.execute(
            "UPDATE exportaciones SET validado = ? WHERE id = ?",
            (1 if validado else 0, exportacion_id),
        )
    conn.commit()
    return jsonify(ok=True, exportacion_id=exportacion_id, validado=validado)


@bp.get('/export')
def exportar_historial():
    """Exporta el historial completo a CSV o XLSX."""
    formato = request.args.get('formato', 'csv').lower()
    if formato not in ('csv', 'xlsx'):
        abort(400, f"Formato no soportado: {formato!r}")

    conn = get_db()
    fd, tmp_name = tempfile.mkstemp(
        suffix=f'.{formato}', prefix='gesdai_historial_',
    )
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        if formato == 'csv':
            csv_handler.exportar_historial(conn, tmp_path)
            mimetype = 'text/csv; charset=utf-8'
        else:
            excel_handler.exportar_historial(conn, tmp_path)
            mimetype = (
                'application/vnd.openxmlformats-officedocument.'
                'spreadsheetml.sheet'
            )
        contenido = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    return send_file(
        io.BytesIO(contenido),
        mimetype=mimetype,
        as_attachment=True,
        download_name=f'historial.{formato}',
    )
