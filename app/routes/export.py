"""Panel de exportación (/export).

Flujo:
  1. GET /export/            → landing con preview del mes actual ya cargada
  2. POST /export/preview    → re-ejecuta preview con el árbol de filtros del front (JSON)
  3. POST /export/generar    → valida que no haya rojos, genera DAT, registra
                               en exportaciones, devuelve el fichero como descarga
  4. POST /export/preview/excel → la preview actual como fichero Excel
"""
from __future__ import annotations

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from app.db import get_db
from app.exporter.pipeline import (
    ConfiguracionIncompletaError,
    ejecutar_generacion,
    ejecutar_preview,
    filtro_mes_actual,
    filtros_desde_json,
    leer_configuracion,
    preview_a_dict,
)
from app.sources import FuenteNoConfiguradaError, get_configured_source

log = logging.getLogger(__name__)
bp = Blueprint('export', __name__, url_prefix='/export')


@bp.get('/')
def index():
    """Landing del panel de exportación.

    Pre-carga la preview del mes en curso para que el operador vea de
    entrada qué hay por exportar, sin tener que tocar filtros. Si hay un
    error de configuración (GESDAI no configurado, faltan claves), se
    flashea y se muestra el panel con la tabla vacía.

    IMPORTANTE: hace `conn.commit()` después del preview para persistir los
    mappings pendientes que el resolver descubre como side-effect al
    clasificar artículos. Sin este commit, la conexión de Flask se cierra
    al terminar la request y SQLite hace rollback automático — el operador
    vería un preview con "DEFAULT" amarillos pero al ir a /mappings/articulos
    no encontraría nada nuevo.
    """
    conn = get_db()
    preview_dict = None
    filtros_iniciales = filtro_mes_actual()

    try:
        config = leer_configuracion(conn)
        source = get_configured_source(conn)
        preview = ejecutar_preview(conn, source, filtros_iniciales, config)
        conn.commit()
        preview_dict = preview_a_dict(preview)
    except FuenteNoConfiguradaError as e:
        flash(str(e), 'error')
    except ConfiguracionIncompletaError as e:
        flash(str(e), 'warning')
    except Exception as e:
        log.exception("Error generando preview inicial")
        flash(f"Error leyendo GESDAI: {e}", 'error')

    return render_template(
        'export.html',
        preview=preview_dict,
        filtros_iniciales={
            'operador': 'AND',
            'condiciones': [
                {
                    'campo': 'fecha',
                    'operador': 'entre',
                    'valor': [
                        filtros_iniciales.condiciones[0].valor[0],  # type: ignore[union-attr,index]
                        filtros_iniciales.condiciones[0].valor[1],  # type: ignore[union-attr,index]
                    ],
                },
            ],
        },
    )


@bp.post('/preview')
def preview():
    """Aplica filtros y devuelve facturas con su estado de resolución."""
    conn = get_db()
    data = request.get_json(silent=True) or {}
    try:
        filtros = filtros_desde_json(data.get('filtros'))
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400

    try:
        config = leer_configuracion(conn)
    except ConfiguracionIncompletaError as e:
        return jsonify(ok=False, error=str(e)), 400

    try:
        source = get_configured_source(conn)
    except FuenteNoConfiguradaError as e:
        return jsonify(ok=False, error=str(e)), 400

    try:
        resultado = ejecutar_preview(conn, source, filtros, config)
        conn.commit()  # persiste mappings pendientes descubiertos por el resolver
    except Exception as e:
        log.exception("Error ejecutando preview")
        return jsonify(ok=False, error=f"Error inesperado: {e}"), 500

    return jsonify(ok=True, **preview_a_dict(resultado))


@bp.post('/generar')
def generar():
    """Genera el DAT, lo registra en exportaciones y devuelve el fichero.

    Falla con 400 si la preview tiene cualquier 🔴 rojo o si no hay
    configuración completa. Devuelve el fichero DAT como descarga directa.
    """
    conn = get_db()
    data = request.get_json(silent=True) or {}

    try:
        filtros = filtros_desde_json(data.get('filtros'))
        config = leer_configuracion(conn)
        source = get_configured_source(conn)
    except (ValueError, ConfiguracionIncompletaError, FuenteNoConfiguradaError) as e:
        return jsonify(ok=False, error=str(e)), 400

    try:
        resultado = ejecutar_generacion(
            conn,
            source,
            filtros,
            config,
            app_version=current_app.config.get('APP_VERSION', ''),
        )
    except ValueError as e:
        return jsonify(ok=False, error=str(e)), 400
    except Exception as e:
        log.exception("Error generando DAT")
        return jsonify(ok=False, error=f"Error inesperado: {e}"), 500

    return jsonify(
        ok=True,
        exportacion_id=resultado.exportacion_id,
        num_facturas=resultado.num_facturas,
        sha256=resultado.sha256,
        download_url=url_for(
            'history.descargar_dat',
            exportacion_id=resultado.exportacion_id,
        ),
    )


@bp.get('/factura/<codigo>')
def factura_detalle(codigo: str):
    """Devuelve el detalle completo de una factura para el modal."""
    conn = get_db()
    try:
        config = leer_configuracion(conn)
        source = get_configured_source(conn)
    except (ConfiguracionIncompletaError, FuenteNoConfiguradaError) as e:
        return jsonify(ok=False, error=str(e)), 400

    from app.mapping.resolver import (
        ClienteSinSubcuentaError,
        Resolver,
    )
    from app.mapping.store import get_cliente_mapping

    # Buscar la factura en el rango completo (sin filtros restrictivos)
    facturas = source.get_facturas(filtros_desde_json(None))
    factura = None
    for f in facturas:
        if f.codigo == codigo:
            factura = f
            break
    if factura is None:
        return jsonify(ok=False, error=f'Factura {codigo!r} no encontrada'), 404

    # Resolver cliente
    resolver = Resolver(conn, config.cuenta_ventas_def)
    cliente_info = {}
    subcuenta = ''
    try:
        res_cli = resolver.resolver_cliente(factura.cliente_codigo)
        subcuenta = res_cli.subcuenta_a3
        cliente_info = {
            'nombre': res_cli.nombre,
            'subcuenta_a3': res_cli.subcuenta_a3,
        }
    except ClienteSinSubcuentaError:
        fila = get_cliente_mapping(conn, factura.cliente_codigo)
        cliente_info = {
            'nombre': fila['nombre'] if fila else factura.cliente_codigo,
            'subcuenta_a3': '',
        }

    # Resolver NIF del cliente
    try:
        cliente_obj = source.get_cliente(factura.cliente_codigo)
        cliente_info['nif'] = cliente_obj.nif or ''
    except (KeyError, Exception):
        cliente_info['nif'] = ''

    # Resolver cada línea
    lineas_out = []
    for linea in factura.lineas:
        res_art = resolver.resolver_articulo(linea.articulo, linea.comentario)
        lineas_out.append({
            'articulo': linea.articulo,
            'comentario': linea.comentario,
            'cantidad': str(linea.cantidad),
            'precio': str(linea.precio),
            'iva': str(linea.iva),
            'total_linea': str(linea.total_linea),
            'cuenta_a3': res_art.cuenta_a3,
            'resolucion_tipo': res_art.tipo.value,
        })

    conn.commit()

    return jsonify(
        ok=True,
        factura={
            'codigo': factura.codigo,
            'serie': factura.serie.strip(),
            'numero': factura.numero.strip(),
            'fecha': factura.fecha.isoformat(),
            'cliente_codigo': factura.cliente_codigo,
            'total_base': str(factura.total_base),
            'total_con_iva': str(factura.total_con_iva),
            'contabil': factura.contabil,
            'ptsbase1': str(factura.ptsbase1),
            'iva1': str(factura.iva1),
            'ptsbase2': str(factura.ptsbase2),
            'iva2': str(factura.iva2),
            'ptsbase3': str(factura.ptsbase3),
            'iva3': str(factura.iva3),
        },
        cliente=cliente_info,
        subcuenta=subcuenta,
        lineas=lineas_out,
    )


@bp.post('/preview/excel')
def preview_excel():
    """Devuelve la preview actual como fichero Excel descargable."""
    import io

    from openpyxl import Workbook

    conn = get_db()
    data = request.get_json(silent=True) or {}

    try:
        filtros = filtros_desde_json(data.get('filtros'))
        config = leer_configuracion(conn)
        source = get_configured_source(conn)
    except (ValueError, ConfiguracionIncompletaError, FuenteNoConfiguradaError) as e:
        return jsonify(ok=False, error=str(e)), 400

    try:
        resultado = ejecutar_preview(conn, source, filtros, config)
        conn.commit()
    except Exception as e:
        log.exception("Error generando preview Excel")
        return jsonify(ok=False, error=f"Error inesperado: {e}"), 500

    wb = Workbook()
    ws = wb.active
    ws.title = 'Preview'
    ws.append([
        'Semáforo', 'Factura', 'Fecha', 'Cliente', 'Subcuenta',
        'Total c/IVA', 'Resolución', 'Mensaje',
    ])
    for entrada in resultado.entradas:
        subcuenta = ''
        if entrada.construccion is not None:
            subcuenta = entrada.construccion.cabecera.cuenta.strip()
        ws.append([
            entrada.color.value,
            f"{entrada.factura.serie.strip()}{entrada.factura.numero.strip()}",
            entrada.factura.fecha.isoformat(),
            entrada.factura.cliente_codigo,
            subcuenta,
            str(entrada.factura.total_con_iva),
            ', '.join(sorted({
                r.tipo.value for r in (
                    entrada.construccion.tipos_resolucion
                    if entrada.construccion else []
                )
            })),
            entrada.mensaje,
        ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='preview_export.xlsx',
    )
