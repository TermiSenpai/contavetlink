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

    No pre-ejecuta la preview: rinde el formulario con el filtro del mes
    actual ya rellenado, y el operador pulsa "Vista previa" para cargar
    las facturas. Evita golpear GESDAI en cada navegación a la página
    (especialmente costoso si el DBF está bloqueado por otros usuarios) y
    permite al operador ajustar filtros antes de la primera lectura.
    """
    filtros_iniciales = filtro_mes_actual()
    return render_template(
        'export.html',
        preview=None,
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


def _construir_detalle_factura(
    factura,
    conn,
    source,
    resolver,
    cliente_cache: dict | None = None,
) -> dict:
    """Construye el dict de detalle de una factura (mismo shape que devuelve
    GET /export/factura/<codigo>). Si se pasa `cliente_cache`, se reutiliza la
    resolución del cliente y su NIF entre facturas de la misma respuesta para
    evitar repetir lecturas del intermediario y de la fuente DBF.
    """
    from app.mapping.resolver import (
        ClienteSinSubcuentaError,
    )
    from app.mapping.store import get_cliente_mapping

    codigo_cli = factura.cliente_codigo
    if cliente_cache is not None and codigo_cli in cliente_cache:
        cached_info, subcuenta = cliente_cache[codigo_cli]
        cliente_info = dict(cached_info)
    else:
        subcuenta = ''
        try:
            res_cli = resolver.resolver_cliente(codigo_cli)
            subcuenta = res_cli.subcuenta_a3
            cliente_info = {
                'nombre': res_cli.nombre,
                'subcuenta_a3': res_cli.subcuenta_a3,
            }
        except ClienteSinSubcuentaError:
            fila = get_cliente_mapping(conn, codigo_cli)
            cliente_info = {
                'nombre': fila['nombre'] if fila else codigo_cli,
                'subcuenta_a3': '',
            }
        try:
            cliente_obj = source.get_cliente(codigo_cli)
            cliente_info['nif'] = cliente_obj.nif or ''
        except Exception:
            cliente_info['nif'] = ''
        if cliente_cache is not None:
            cliente_cache[codigo_cli] = (dict(cliente_info), subcuenta)

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

    return {
        'factura': {
            'codigo': factura.codigo,
            'serie': factura.serie.strip(),
            'numero': factura.numero.strip(),
            'fecha': factura.fecha.isoformat() if factura.fecha else '',
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
        'cliente': cliente_info,
        'subcuenta': subcuenta,
        'lineas': lineas_out,
    }


@bp.get('/factura/<codigo>')
def factura_detalle(codigo: str):
    """Devuelve el detalle completo de una factura para el modal.

    Usado como fallback cuando el cache de precarga del front (poblado por
    `/export/preview/detalles`) no contiene la factura — por ejemplo si la
    precarga falló o si el usuario abre el modal antes de que se haya
    disparado la primera preview.
    """
    conn = get_db()
    try:
        config = leer_configuracion(conn)
        source = get_configured_source(conn)
    except (ConfiguracionIncompletaError, FuenteNoConfiguradaError) as e:
        return jsonify(ok=False, error=str(e)), 400

    from app.mapping.resolver import Resolver

    # Buscar la factura en el rango completo (sin filtros restrictivos)
    facturas = source.get_facturas(filtros_desde_json(None))
    factura = next((f for f in facturas if f.codigo == codigo), None)
    if factura is None:
        return jsonify(ok=False, error=f'Factura {codigo!r} no encontrada'), 404

    resolver = Resolver(conn, config.cuenta_ventas_def)
    detalle = _construir_detalle_factura(factura, conn, source, resolver)
    conn.commit()

    return jsonify(ok=True, **detalle)


@bp.post('/preview/detalles')
def preview_detalles():
    """Devuelve detalles completos de todas las facturas que cumplen los
    filtros, en una sola pasada. Pensado para que el front lo dispare en
    segundo plano tras `/export/preview` y abra el modal de cada fila sin
    esperar al backend.

    Comparte un cache local de clientes entre todas las facturas para no
    repetir `get_cliente_mapping` ni `source.get_cliente` por cada factura
    del mismo cliente.
    """
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

    from app.mapping.resolver import Resolver

    resolver = Resolver(conn, config.cuenta_ventas_def)
    cliente_cache: dict = {}

    try:
        facturas = source.get_facturas(filtros)
        detalles = {
            f.codigo: _construir_detalle_factura(
                f, conn, source, resolver, cliente_cache=cliente_cache,
            )
            for f in facturas
        }
    except Exception as e:
        log.exception("Error precargando detalles de facturas")
        return jsonify(ok=False, error=f"Error inesperado: {e}"), 500

    conn.commit()
    return jsonify(ok=True, detalles=detalles)


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
            entrada.factura.fecha.isoformat() if entrada.factura.fecha else '',
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
