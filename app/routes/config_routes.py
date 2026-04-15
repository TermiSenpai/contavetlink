"""Panel de configuración (/config).

Permite al usuario configurar:
  - dbf_path           → ruta al directorio de DBFs de GESDAI
  - exports_path       → directorio donde se guardan los DAT generados
  - cuenta_ventas_def  → cuenta 700 por defecto cuando un artículo no resuelve
  - ejercicio          → año contable activo
  - cod_empresa        → código de empresa en a3ASESOR (1–99999)
  - importe_formato    → A (escala implícita) | B (decimal explícito)

`POST /verificar-dbf` recibe una ruta por JSON e intenta abrir los DBFs en
READ_ONLY para dar feedback rápido en la UI antes de guardar.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for

from app.db import (
    SETTING_COD_EMPRESA,
    SETTING_CUENTA_VENTAS_DEF,
    SETTING_DBF_PATH,
    SETTING_EJERCICIO,
    SETTING_EXPORTS_PATH,
    SETTING_IMPORTE_FORMATO,
    get_all_settings,
    get_db,
    set_setting,
)
from app.mapping.store import SubcuentaInvalidaError, validar_subcuenta_ingreso
from app.sources.dbf_source import (
    DbfLockedError,
    DbfNotFoundError,
    DbfSchemaError,
    DbfSource,
)

log = logging.getLogger(__name__)
bp = Blueprint('config', __name__, url_prefix='/config')


@bp.get('/')
def index():
    valores = get_all_settings(get_db())
    return render_template('config.html', valores=valores)


@bp.post('/')
def save():
    """Guarda los valores del formulario en la tabla `config` del SQLite.

    Valida cada campo antes de tocar la BD. Si cualquiera falla, flashea el
    error y redirige de vuelta al formulario (el GET re-lee los valores
    actuales, así que los válidos persisten). Los POST los gestionamos con
    flash + redirect (patrón Post/Redirect/Get) para que un refresh no
    vuelva a enviar el formulario.
    """
    form = request.form
    errores: list[str] = []
    payload: dict[str, str] = {}

    dbf_path = (form.get('dbf_path') or '').strip()
    if not dbf_path:
        errores.append("La ruta a los DBFs no puede estar vacía.")
    elif not Path(dbf_path).is_dir():
        errores.append(f"La ruta a los DBFs no existe o no es un directorio: {dbf_path}")
    else:
        payload[SETTING_DBF_PATH] = dbf_path

    exports_path = (form.get('exports_path') or '').strip()
    if not exports_path:
        errores.append("El directorio de salida no puede estar vacío.")
    else:
        payload[SETTING_EXPORTS_PATH] = exports_path

    cod_empresa_raw = (form.get('cod_empresa') or '').strip()
    try:
        cod_empresa = int(cod_empresa_raw)
        if not (1 <= cod_empresa <= 99999):
            raise ValueError
        payload[SETTING_COD_EMPRESA] = str(cod_empresa)
    except ValueError:
        errores.append(
            f"Código de empresa inválido: {cod_empresa_raw!r} (1–99999)."
        )

    cuenta_ventas = (form.get('cuenta_ventas_def') or '').strip()
    try:
        validar_subcuenta_ingreso(cuenta_ventas)
        payload[SETTING_CUENTA_VENTAS_DEF] = cuenta_ventas
    except SubcuentaInvalidaError as e:
        errores.append(str(e))

    ejercicio_raw = (form.get('ejercicio') or '').strip()
    try:
        ejercicio = int(ejercicio_raw)
        if not (2000 <= ejercicio <= 2099):
            raise ValueError
        payload[SETTING_EJERCICIO] = str(ejercicio)
    except ValueError:
        errores.append(
            f"Ejercicio inválido: {ejercicio_raw!r} (2000–2099)."
        )

    importe_formato = (form.get('importe_formato') or '').strip()
    if importe_formato not in ('A', 'B'):
        errores.append(
            f"Formato de importe debe ser 'A' o 'B', recibido: {importe_formato!r}"
        )
    else:
        payload[SETTING_IMPORTE_FORMATO] = importe_formato

    if errores:
        for err in errores:
            flash(err, 'error')
        return redirect(url_for('config.index'))

    conn = get_db()
    for clave, valor in payload.items():
        set_setting(conn, clave, valor)
    conn.commit()

    log.info(
        "Configuración guardada",
        extra={'action': 'config_save', 'claves': list(payload.keys())},
    )
    flash("Configuración guardada correctamente.", 'success')
    return redirect(url_for('config.index'))


@bp.post('/verificar-dbf')
def verificar_dbf():
    """Intenta abrir los DBFs en READ_ONLY para feedback antes de guardar.

    Recibe `{dbf_path: ...}` por JSON. Devuelve siempre status 200 con
    `{ok, error, n_clientes, n_articulos}` — los errores de negocio no son
    fallos HTTP, son respuestas informativas para que la UI los pinte.
    """
    data = request.get_json(silent=True) or {}
    ruta = (data.get('dbf_path') or '').strip()
    if not ruta:
        return jsonify(ok=False, error="Ruta vacía"), 200

    try:
        src = DbfSource(ruta)
    except DbfNotFoundError as e:
        return jsonify(ok=False, error=f"No encontrado: {e}")
    except DbfLockedError as e:
        return jsonify(ok=False, error=str(e))
    except DbfSchemaError as e:
        return jsonify(ok=False, error=f"Esquema inválido: {e}")
    except Exception as e:
        log.exception("Error verificando DBF en %s", ruta)
        return jsonify(ok=False, error=f"Error inesperado: {e}"), 500

    try:
        n_clientes = len(src.get_clientes())
        n_articulos = len(src.get_articulos())
    except Exception as e:
        log.exception("Error leyendo catálogos tras verificar %s", ruta)
        return jsonify(ok=False, error=f"Apertura OK pero lectura falló: {e}")

    return jsonify(
        ok=True,
        dbf_path=ruta,
        n_clientes=n_clientes,
        n_articulos=n_articulos,
    )
