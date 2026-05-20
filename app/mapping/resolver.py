"""Pipeline de resolución artículo → cuenta contable.

Orden estricto (Sección 6.4 del plan):
    1. mappings_articulos con revisado=1  → tipo='mapping'
    2. keyword matching activo            → tipo='keyword' (persiste pendiente)
    3. cuenta por defecto (config)        → tipo='default'  (persiste pendiente)

Nunca devuelve None — siempre hay una cuenta. El `tipo` permite al semáforo
de Fase 4 distinguir verde (mapping revisado) / amarillo (keyword o default)
de una forma que el operador puede interpretar de un vistazo.

Efecto colateral controlado: los caminos `keyword` y `default` persisten una
fila pendiente (`revisado=0`) en `mappings_articulos`. Esto deja rastro del
artículo para que aparezca en la UI con su cuenta propuesta, listo para que
el operador la confirme.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum

from app.mapping.keywords import Keyword, load_keywords, match
from app.mapping.store import (
    get_articulo_mapping,
    get_cliente_mapping,
    upsert_articulo_mapping,
    validar_subcuenta_ingreso,
)

log = logging.getLogger(__name__)


class TipoResolucion(str, Enum):
    MAPPING = 'mapping'
    KEYWORD = 'keyword'
    DEFAULT = 'default'


@dataclass(frozen=True)
class ResolucionArticulo:
    cuenta_a3: str
    tipo: TipoResolucion


@dataclass(frozen=True)
class ResolucionCliente:
    subcuenta_a3: str
    nombre: str


class ClienteSinSubcuentaError(ValueError):
    """El cliente no tiene subcuenta a3ASESOR — bloquea exportación (🔴 rojo)."""


class Resolver:
    """Resolución de artículos y clientes con dependencias inyectadas.

    La lista de keywords se carga una sola vez en el constructor. Si el
    operador añade/modifica keywords durante la sesión, habrá que instanciar
    un nuevo Resolver (barato: es una sola query).
    """

    def __init__(self, conn: sqlite3.Connection, cuenta_default: str) -> None:
        validar_subcuenta_ingreso(cuenta_default)
        self.conn = conn
        self.cuenta_default = cuenta_default
        self._keywords: list[Keyword] = load_keywords(conn, solo_activos=True)

    # ─── Artículos ─────────────────────────────────────────────────────────

    def resolver_articulo(
        self,
        clave_raw: str | None,
        comentario: str = '',
    ) -> ResolucionArticulo:
        """Resuelve una clave de artículo a su cuenta contable.

        Aplica el pipeline en orden: mapping → keyword → default. Si entra
        por keyword o default, persiste el resultado en `mappings_articulos`
        como pendiente de revisión para que aparezca en la UI.

        Para líneas de texto libre (clave vacía) las keywords se evalúan
        contra el `comentario` de la línea. Esto permite al operador definir
        keywords sobre descripciones libres (p.ej. "revision pre-quirurgica"
        → 700020) y que se apliquen automáticamente a futuras facturas con
        el mismo texto.
        """
        clave = (clave_raw or '').strip()

        if clave:
            existente = get_articulo_mapping(self.conn, clave)
            if (
                existente is not None
                and existente['revisado'] == 1
                and existente['cuenta_a3']
            ):
                return ResolucionArticulo(
                    existente['cuenta_a3'], TipoResolucion.MAPPING,
                )

            # En líneas con clave, las keywords se prueban primero contra la
            # clave (catálogo: 'CHIP', 'PASAPORTE'...) y, si no hay
            # coincidencia, contra el comentario por si la descripción libre
            # añade contexto útil ("CHIP-OFR" + comentario "promocion").
            kw = match(clave, self._keywords) or match(comentario, self._keywords)
            if kw is not None:
                upsert_articulo_mapping(
                    self.conn,
                    clave=clave,
                    descripcion=clave[:255],
                    cuenta_a3=kw.cuenta_a3,
                )
                return ResolucionArticulo(kw.cuenta_a3, TipoResolucion.KEYWORD)

            # Default: persistimos como pendiente con la cuenta genérica.
            upsert_articulo_mapping(
                self.conn,
                clave=clave,
                descripcion=clave[:255],
                cuenta_a3=self.cuenta_default,
            )
        elif comentario:
            # Línea de texto libre: keywords se evalúan contra la descripción
            # libre. No hay clave que persistir — la asociación
            # comentario → cuenta vive sólo en `keywords_articulos`.
            kw = match(comentario, self._keywords)
            if kw is not None:
                return ResolucionArticulo(kw.cuenta_a3, TipoResolucion.KEYWORD)

        return ResolucionArticulo(self.cuenta_default, TipoResolucion.DEFAULT)

    # ─── Clientes ──────────────────────────────────────────────────────────

    def resolver_cliente(self, codigo: str) -> ResolucionCliente:
        """Devuelve la subcuenta 430XXX + nombre del cliente.

        Lanza `ClienteSinSubcuentaError` si:
          - el cliente no existe en mappings_clientes (no sincronizado)
          - el cliente existe pero `subcuenta_a3` es NULL o vacía

        Esto produce un 🔴 rojo en el semáforo y bloquea exportación.
        """
        fila = get_cliente_mapping(self.conn, codigo)
        if fila is None:
            raise ClienteSinSubcuentaError(
                f"Cliente {codigo!r} no existe en mappings_clientes. "
                f"Sincroniza el catálogo desde GESDAI antes de exportar."
            )
        subcuenta = fila['subcuenta_a3']
        if not subcuenta:
            raise ClienteSinSubcuentaError(
                f"Cliente {codigo!r} ({fila['nombre']}) sin subcuenta asignada"
            )
        return ResolucionCliente(
            subcuenta_a3=subcuenta,
            nombre=fila['nombre'],
        )
