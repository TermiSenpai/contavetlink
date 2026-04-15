"""Clasificación de semáforo para la vista previa de exportación.

Cada factura se evalúa y se le asigna un color según las reglas del plan
(Sección 4.5):

  🟢 verde     — cliente revisado Y todos los artículos resueltos por mapping
  🟡 amarillo  — exportable pero con incertidumbre (keyword, default,
                 o cliente sin revisar)
  🔴 rojo      — cliente sin subcuenta a3 → BLOQUEA exportación
  ⚪ gris      — factura ya presente en `exportaciones_detalle` → EXCLUIDA
                 automáticamente (nunca entra al DAT)

Este módulo es el único punto donde se decide el color — si mañana las
reglas cambian (ej. cfactura.CONTABIL ⚠️ pasa a ser bloqueante), aquí se
ajustan sin tocar el builder ni las rutas.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from enum import Enum

from app.exporter.builder import (
    Builder,
    CuadreError,
    FacturaYaExportadaError,
    ResultadoConstruccion,
)
from app.mapping.resolver import (
    ClienteSinSubcuentaError,
    Resolver,
    TipoResolucion,
)
from app.mapping.store import get_cliente_mapping
from app.sources.base import Factura

log = logging.getLogger(__name__)


class ColorSemaforo(str, Enum):
    VERDE = 'verde'
    AMARILLO = 'amarillo'
    ROJO = 'rojo'
    GRIS = 'gris'


@dataclass
class EntradaPreview:
    """Una fila de la tabla preview — lo que el JS recibe por factura."""
    factura: Factura
    color: ColorSemaforo
    construccion: ResultadoConstruccion | None = None   # None si rojo/gris
    mensaje: str = ''
    advertencia_contabil: bool = False                   # ⚠️ informativo
    errores: list[str] = field(default_factory=list)

    @property
    def exportable(self) -> bool:
        return self.color in (ColorSemaforo.VERDE, ColorSemaforo.AMARILLO)


@dataclass
class ResumenPreview:
    total: int = 0
    verdes: int = 0
    amarillos: int = 0
    rojos: int = 0
    grises: int = 0


def clasificar_factura(
    factura: Factura,
    builder: Builder,
    conn: sqlite3.Connection,
    resolver: Resolver,
) -> EntradaPreview:
    """Aplica todas las reglas de semáforo a una factura concreta.

    Nunca lanza — los errores se capturan y se reflejan en el color/mensaje.
    Es responsabilidad del caller iterar sobre todas las facturas del
    filtro aplicado.
    """
    entrada = EntradaPreview(
        factura=factura,
        color=ColorSemaforo.GRIS,  # default optimista para errores no clasificables
        advertencia_contabil=bool(factura.contabil),
    )

    # 1. ¿Ya exportada? → GRIS (se excluye del DAT automáticamente)
    try:
        builder._validar_no_exportada(factura)
    except FacturaYaExportadaError:
        entrada.color = ColorSemaforo.GRIS
        entrada.mensaje = "Ya presente en un DAT anterior."
        return entrada

    # 2. Intentar construcción completa. Si falla por cliente → rojo;
    #    si falla por cuadre → rojo con mensaje explícito. Cualquier otra
    #    excepción (sqlite, corrupción, bug) también cae a rojo con el
    #    mensaje — una factura mala NO debe abortar el preview completo.
    try:
        construccion = builder.construir_registros(factura)
    except ClienteSinSubcuentaError as e:
        entrada.color = ColorSemaforo.ROJO
        entrada.mensaje = str(e)
        entrada.errores.append(str(e))
        return entrada
    except CuadreError as e:
        entrada.color = ColorSemaforo.ROJO
        entrada.mensaje = f"Descuadre: {e}"
        entrada.errores.append(str(e))
        return entrada
    except Exception as e:
        log.exception(
            "Error inesperado construyendo registros para factura %s",
            factura.codigo,
        )
        entrada.color = ColorSemaforo.ROJO
        entrada.mensaje = f"Error inesperado: {e}"
        entrada.errores.append(f"{type(e).__name__}: {e}")
        return entrada

    entrada.construccion = construccion

    # 3. Verde vs amarillo según resolución de artículos + estado revisado
    fila_cliente = get_cliente_mapping(conn, factura.cliente_codigo)
    cliente_revisado = bool(fila_cliente and fila_cliente['revisado'] == 1)
    todos_mapping = all(
        r.tipo == TipoResolucion.MAPPING
        for r in construccion.tipos_resolucion
    )

    if cliente_revisado and todos_mapping and construccion.tipos_resolucion:
        entrada.color = ColorSemaforo.VERDE
    else:
        entrada.color = ColorSemaforo.AMARILLO
        razones = []
        if not cliente_revisado:
            razones.append("cliente no revisado")
        if not todos_mapping:
            razones.append("algún artículo por keyword/default")
        if not construccion.tipos_resolucion:
            razones.append("factura sin líneas")
        entrada.mensaje = ", ".join(razones) if razones else ""

    return entrada


def resumir(entradas: list[EntradaPreview]) -> ResumenPreview:
    resumen = ResumenPreview(total=len(entradas))
    for e in entradas:
        if e.color == ColorSemaforo.VERDE:
            resumen.verdes += 1
        elif e.color == ColorSemaforo.AMARILLO:
            resumen.amarillos += 1
        elif e.color == ColorSemaforo.ROJO:
            resumen.rojos += 1
        elif e.color == ColorSemaforo.GRIS:
            resumen.grises += 1
    return resumen
