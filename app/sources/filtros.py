"""Motor de evaluación del árbol `Filtros` AND/OR.

Vive en `sources/` porque opera sobre los modelos de `base.py` (`Factura`,
`Filtros`, `Condicion`) — no es específico de la fuente DBF y se reutiliza tal
cual cuando aparezcan futuras implementaciones (`excel_source`, `csv_source`).

Campos filtrables soportados en v1.0 (Sección 3.2 del plan):

    fecha     → factura.fecha       — IGUAL, ENTRE, ANTES_DE, DESPUES_DE
    cliente   → factura.cliente_codigo — IGUAL, NO_IGUAL, CONTIENE
    serie     → factura.serie       — IGUAL, NO_IGUAL
    importe   → factura.total_con_iva — MAYOR_QUE, MENOR_QUE, ENTRE
    resolucion → no aplica aquí (depende del estado del mapping)

`resolucion` se ignora en este nivel (devuelve siempre True): el filtrado por
estado de resolución se aplica más tarde, sobre el resultado ya enriquecido
con la información del intermediario, en la capa de routes/.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.sources.base import (
    Condicion,
    Factura,
    Filtros,
    OperadorCondicion,
    OperadorFiltro,
)

CAMPOS_VALIDOS = frozenset({'fecha', 'cliente', 'serie', 'importe', 'resolucion'})


def aplica_filtros(filtros: Filtros, factura: Factura) -> bool:
    """Evalúa el árbol de filtros contra una factura.

    Un árbol vacío (sin condiciones) devuelve siempre True — semántica de
    "no filtrar".
    """
    if not filtros.condiciones:
        return True

    resultados = (_evaluar_item(item, factura) for item in filtros.condiciones)
    if filtros.operador == OperadorFiltro.AND:
        return all(resultados)
    if filtros.operador == OperadorFiltro.OR:
        return any(resultados)
    raise ValueError(f"Operador de filtro desconocido: {filtros.operador!r}")


def _evaluar_item(item: Condicion | Filtros, factura: Factura) -> bool:
    if isinstance(item, Filtros):
        return aplica_filtros(item, factura)
    if isinstance(item, Condicion):
        return _evaluar_condicion(item, factura)
    raise TypeError(f"Item de filtro no soportado: {type(item).__name__}")


def _evaluar_condicion(cond: Condicion, factura: Factura) -> bool:
    if cond.campo not in CAMPOS_VALIDOS:
        raise ValueError(
            f"Campo de filtro no soportado: {cond.campo!r} "
            f"(válidos: {sorted(CAMPOS_VALIDOS)})"
        )
    if cond.campo == 'resolucion':
        return True

    actual = _extraer_campo(factura, cond.campo)
    # Una factura sin FECHA siempre pasa el filtro de fecha — no podemos
    # ubicarla en un rango, pero el contable debe verla en preview (ROJO)
    # para corregirla en GESDAI. Sin esto, las facturas mal introducidas
    # desaparecen silenciosamente y crean huecos en la secuencia.
    if cond.campo == 'fecha' and actual is None:
        return True
    return _comparar(actual, cond.operador, cond.valor)


def _extraer_campo(factura: Factura, campo: str) -> Any:
    if campo == 'fecha':
        return factura.fecha
    if campo == 'cliente':
        return factura.cliente_codigo
    if campo == 'serie':
        return factura.serie
    if campo == 'importe':
        return factura.total_con_iva
    raise ValueError(f"Campo no soportado: {campo!r}")


def _comparar(actual: Any, operador: OperadorCondicion, valor: Any) -> bool:
    """Compara `actual` con `valor` usando el operador. Normaliza tipos en el borde."""
    if operador == OperadorCondicion.IGUAL:
        return _eq(actual, valor)
    if operador == OperadorCondicion.NO_IGUAL:
        return not _eq(actual, valor)
    if operador == OperadorCondicion.CONTIENE:
        return _contiene(actual, valor)
    if operador == OperadorCondicion.ENTRE:
        lo, hi = _normalizar_rango(actual, valor)
        return lo <= actual <= hi
    if operador == OperadorCondicion.ANTES_DE:
        return actual < _normalizar(actual, valor)
    if operador == OperadorCondicion.DESPUES_DE:
        return actual > _normalizar(actual, valor)
    if operador == OperadorCondicion.MAYOR_QUE:
        return actual > _normalizar(actual, valor)
    if operador == OperadorCondicion.MENOR_QUE:
        return actual < _normalizar(actual, valor)
    raise ValueError(f"Operador de condición desconocido: {operador!r}")


def _eq(actual: Any, valor: Any) -> bool:
    return actual == _normalizar(actual, valor)


def _contiene(actual: Any, valor: Any) -> bool:
    if actual is None:
        return False
    return str(valor).lower() in str(actual).lower()


def _normalizar(actual: Any, valor: Any) -> Any:
    """Normaliza `valor` al tipo de `actual` cuando llega como string desde la UI."""
    if isinstance(actual, date) and isinstance(valor, str):
        return date.fromisoformat(valor)
    if isinstance(actual, Decimal) and not isinstance(valor, Decimal):
        return Decimal(str(valor))
    return valor


def _normalizar_rango(actual: Any, valor: Any) -> tuple[Any, Any]:
    if not isinstance(valor, tuple | list) or len(valor) != 2:
        raise ValueError(
            f"Operador ENTRE requiere una tupla (lo, hi); recibido {valor!r}"
        )
    lo, hi = valor
    return _normalizar(actual, lo), _normalizar(actual, hi)
