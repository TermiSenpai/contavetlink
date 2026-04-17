"""Paneles de mappings — clientes (/mappings/clientes) y artículos (/mappings/articulos).

Las dos tablas comparten el mismo ciclo de vida:
  1. Sincronizar desde GESDAI (`POST /sync`) — trae nuevos, refresca no
     revisados, nunca toca revisados
  2. Listar con filtro todos/pendientes/revisados (`GET /`)
  3. Editar subcuenta inline (`POST /<codigo>`) — JSON, validación regex
  4. Marcar revisado (`POST /<codigo>/revisar`) — JSON
  5. Import/export CSV/Excel — se cablea al final del bloque

Los POSTs de edición responden JSON para que el JS vanilla del front pueda
actualizar la fila sin recargar la página.
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
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.db import get_db
from app.io import csv_handler, excel_handler
from app.mapping.store import (
    CuentaDuplicadaError,
    SubcuentaInvalidaError,
    list_articulos_mappings,
    list_clientes_mappings,
    marcar_articulo_revisado,
    marcar_cliente_revisado,
    progreso_articulos,
    progreso_clientes,
    set_cuenta_articulo,
    set_subcuenta_cliente,
)
from app.mapping.sync import sync_articulos, sync_clientes
from app.sources import FuenteNoConfiguradaError, get_configured_source

log = logging.getLogger(__name__)
bp = Blueprint('mappings', __name__, url_prefix='/mappings')


# ─── Clientes ──────────────────────────────────────────────────────────────


@bp.get('/clientes')
def clientes_index():
    conn = get_db()
    filtro = request.args.get('filtro', 'todos')
    try:
        clientes = list_clientes_mappings(conn, filtro)
    except ValueError:
        flash(f"Filtro desconocido: {filtro!r}", 'error')
        clientes = list_clientes_mappings(conn, 'todos')
        filtro = 'todos'

    revisados, total = progreso_clientes(conn)
    return render_template(
        'mappings_clientes.html',
        clientes=clientes,
        progreso={'revisados': revisados, 'total': total},
        filtro_actual=filtro,
    )


@bp.post('/clientes/sync')
def clientes_sync():
    """Sincroniza mappings_clientes con los clientes de GESDAI."""
    conn = get_db()
    try:
        source = get_configured_source(conn)
    except FuenteNoConfiguradaError as e:
        flash(str(e), 'error')
        return redirect(url_for('config.index'))
    except Exception as e:
        log.exception("Error abriendo fuente para sync clientes")
        flash(f"No se pudo abrir GESDAI: {e}", 'error')
        return redirect(url_for('mappings.clientes_index'))

    resultado = sync_clientes(conn, source)
    flash(
        f"Sincronización: {resultado.insertados} nuevos, "
        f"{resultado.actualizados} actualizados, "
        f"{resultado.saltados_revisados} revisados intactos.",
        'success',
    )
    return redirect(url_for('mappings.clientes_index'))


@bp.post('/clientes/<codigo>')
def clientes_update(codigo: str):
    """Actualiza la subcuenta de un cliente y lo marca revisado.

    Único usuario (Anguix) ⇒ escribir = revisar. Devuelve 409 si la subcuenta
    ya está asignada a otro cliente.
    """
    data = request.get_json(silent=True) or request.form
    subcuenta = (data.get('subcuenta_a3') or '').strip()
    conn = get_db()
    try:
        set_subcuenta_cliente(conn, codigo, subcuenta)
        marcar_cliente_revisado(conn, codigo, revisado=True)
    except SubcuentaInvalidaError as e:
        return jsonify(ok=False, error=str(e)), 400
    except CuentaDuplicadaError as e:
        return jsonify(ok=False, error=str(e)), 409
    except KeyError:
        return jsonify(ok=False, error=f"Cliente no encontrado: {codigo}"), 404
    conn.commit()
    revisados, total = progreso_clientes(conn)
    return jsonify(
        ok=True,
        codigo=codigo,
        subcuenta_a3=subcuenta,
        revisado=True,
        progreso={'revisados': revisados, 'total': total},
    )


@bp.post('/clientes/<codigo>/revisar')
def clientes_marcar_revisado(codigo: str):
    data = request.get_json(silent=True) or request.form
    revisado_raw = data.get('revisado', True)
    revisado = revisado_raw if isinstance(revisado_raw, bool) else str(revisado_raw).lower() not in ('0', 'false', 'no')
    conn = get_db()
    try:
        marcar_cliente_revisado(conn, codigo, revisado=revisado)
    except KeyError:
        return jsonify(ok=False, error=f"Cliente no encontrado: {codigo}"), 404
    conn.commit()
    return jsonify(ok=True, codigo=codigo, revisado=revisado)


@bp.post('/clientes/import')
def clientes_import():
    """Acepta CSV o XLSX. No sobreescribe filas con revisado=1."""
    return _handle_import(
        'clientes',
        csv_importer=csv_handler.importar_mappings_clientes,
        xlsx_importer=excel_handler.importar_mappings_clientes,
        redirect_url=url_for('mappings.clientes_index'),
    )


@bp.get('/clientes/export')
def clientes_export():
    formato = request.args.get('formato', 'csv').lower()
    return _handle_export(
        nombre_base='mappings_clientes',
        formato=formato,
        csv_exporter=csv_handler.exportar_mappings_clientes,
        xlsx_exporter=excel_handler.exportar_mappings_clientes,
    )


# ─── Artículos ─────────────────────────────────────────────────────────────


@bp.get('/articulos')
def articulos_index():
    conn = get_db()
    filtro = request.args.get('filtro', 'todos')
    try:
        articulos = list_articulos_mappings(conn, filtro)
    except ValueError:
        flash(f"Filtro desconocido: {filtro!r}", 'error')
        articulos = list_articulos_mappings(conn, 'todos')
        filtro = 'todos'

    revisados, total = progreso_articulos(conn)
    return render_template(
        'mappings_articulos.html',
        articulos=articulos,
        progreso={'revisados': revisados, 'total': total},
        filtro_actual=filtro,
    )


@bp.post('/articulos/sync')
def articulos_sync():
    conn = get_db()
    try:
        source = get_configured_source(conn)
    except FuenteNoConfiguradaError as e:
        flash(str(e), 'error')
        return redirect(url_for('config.index'))
    except Exception as e:
        log.exception("Error abriendo fuente para sync artículos")
        flash(f"No se pudo abrir GESDAI: {e}", 'error')
        return redirect(url_for('mappings.articulos_index'))

    resultado = sync_articulos(conn, source)
    flash(
        f"Sincronización: {resultado.insertados} nuevos, "
        f"{resultado.actualizados} actualizados, "
        f"{resultado.saltados_revisados} revisados intactos.",
        'success',
    )
    return redirect(url_for('mappings.articulos_index'))


@bp.post('/articulos/<clave>')
def articulos_update(clave: str):
    """Actualiza la cuenta de un artículo y lo marca revisado.

    Único usuario ⇒ escribir = revisar. Devuelve 409 si la cuenta ya está
    asignada a otro artículo.
    """
    data = request.get_json(silent=True) or request.form
    cuenta = (data.get('cuenta_a3') or '').strip()
    conn = get_db()
    try:
        set_cuenta_articulo(conn, clave, cuenta)
        marcar_articulo_revisado(conn, clave, revisado=True)
    except SubcuentaInvalidaError as e:
        return jsonify(ok=False, error=str(e)), 400
    except CuentaDuplicadaError as e:
        return jsonify(ok=False, error=str(e)), 409
    except KeyError:
        return jsonify(ok=False, error=f"Artículo no encontrado: {clave}"), 404
    conn.commit()
    revisados, total = progreso_articulos(conn)
    return jsonify(
        ok=True,
        clave=clave,
        cuenta_a3=cuenta,
        revisado=True,
        progreso={'revisados': revisados, 'total': total},
    )


@bp.post('/articulos/<clave>/revisar')
def articulos_marcar_revisado(clave: str):
    data = request.get_json(silent=True) or request.form
    revisado_raw = data.get('revisado', True)
    revisado = revisado_raw if isinstance(revisado_raw, bool) else str(revisado_raw).lower() not in ('0', 'false', 'no')
    conn = get_db()
    try:
        marcar_articulo_revisado(conn, clave, revisado=revisado)
    except KeyError:
        return jsonify(ok=False, error=f"Artículo no encontrado: {clave}"), 404
    conn.commit()
    return jsonify(ok=True, clave=clave, revisado=revisado)


@bp.post('/articulos/import')
def articulos_import():
    return _handle_import(
        'articulos',
        csv_importer=csv_handler.importar_mappings_articulos,
        xlsx_importer=excel_handler.importar_mappings_articulos,
        redirect_url=url_for('mappings.articulos_index'),
    )


@bp.get('/articulos/export')
def articulos_export():
    formato = request.args.get('formato', 'csv').lower()
    return _handle_export(
        nombre_base='mappings_articulos',
        formato=formato,
        csv_exporter=csv_handler.exportar_mappings_articulos,
        xlsx_exporter=excel_handler.exportar_mappings_articulos,
    )


# ─── Helpers de import/export ──────────────────────────────────────────────


def _handle_import(kind: str, *, csv_importer, xlsx_importer, redirect_url: str):
    """Procesa un POST multipart con un fichero CSV o XLSX.

    Los importadores del store ya escriben sus errores por fila en
    `ResultadoImport.errores`; los flasheamos sin abortar el lote completo.
    """
    fichero = request.files.get('fichero')
    if fichero is None or fichero.filename == '':
        flash("No se adjuntó ningún fichero.", 'error')
        return redirect(redirect_url)

    nombre = fichero.filename or ''
    extension = Path(nombre).suffix.lower()
    if extension not in ('.csv', '.xlsx'):
        flash(f"Formato no soportado: {extension or '(sin extensión)'}", 'error')
        return redirect(redirect_url)

    # Guardamos a tmp para que el importador lea de Path. Usamos mkstemp +
    # close explícito para evitar el doble-handle que NamedTemporaryFile
    # puede provocar en Windows (tempfile abierto + Werkzeug abriendo otra
    # handle al mismo path con `open('wb')`).
    fd, tmp_name = tempfile.mkstemp(suffix=extension, prefix='gesdai_import_')
    os.close(fd)
    tmp_path = Path(tmp_name)
    fichero.save(str(tmp_path))

    conn = get_db()
    try:
        if extension == '.csv':
            resultado = csv_importer(conn, tmp_path)
        else:
            resultado = xlsx_importer(conn, tmp_path)
    except ValueError as e:
        flash(f"Error importando {nombre}: {e}", 'error')
        return redirect(redirect_url)
    finally:
        tmp_path.unlink(missing_ok=True)

    msg = (
        f"Import {kind}: {resultado.insertados} nuevos, "
        f"{resultado.actualizados} actualizados, "
        f"{resultado.saltados_revisados} revisados intactos."
    )
    if resultado.errores:
        # Mostramos solo los primeros 5 para no saturar la página
        extra = '; '.join(resultado.errores[:5])
        if len(resultado.errores) > 5:
            extra += f" (+{len(resultado.errores) - 5} más)"
        flash(f"{msg} Errores: {extra}", 'warning')
    else:
        flash(msg, 'success')
    return redirect(redirect_url)


def _handle_export(*, nombre_base: str, formato: str, csv_exporter, xlsx_exporter):
    """Genera el fichero en memoria y lo sirve como descarga."""
    if formato not in ('csv', 'xlsx'):
        abort(400, f"Formato no soportado: {formato!r}")

    conn = get_db()
    fd, tmp_name = tempfile.mkstemp(suffix=f'.{formato}', prefix='gesdai_export_')
    os.close(fd)
    tmp_path = Path(tmp_name)

    try:
        if formato == 'csv':
            csv_exporter(conn, tmp_path)
            mimetype = 'text/csv; charset=utf-8'
        else:
            xlsx_exporter(conn, tmp_path)
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
        download_name=f'{nombre_base}.{formato}',
    )
