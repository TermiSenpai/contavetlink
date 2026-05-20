"""Constructor de registros lógicos SUENLACE a partir de facturas resueltas.

Por cada `Factura` produce:
  - 1 registro Cabecera IVA  (tipreg=1, orden='I')
  - N registros Detalle IVA  (tipreg=9), uno por cada PTSBASE > 0
    El último detalle lleva orden='U', los anteriores 'M'.

Validaciones (Sección 8 Fase 3 del plan):
  - sum(bases) + sum(cuotas_iva) + sum(cuotas_rec) − retencion ≈ TOTCONIVA
    con tolerancia 0,02€
  - cliente debe tener `subcuenta_a3` asignada (si no → 🔴 rojo)
  - factura no puede estar ya registrada en `exportaciones_detalle`

Decisión v1.0: todos los detalles usan `cuenta_ventas_def` (de la tabla
`config` del intermediario), NO la cuenta resuelta por artículo. Esto casa
con la regla del plan "uno por cada PTSBASE>0" — si cada línea pudiera
tener cuenta distinta, habría que emitir más de tres detalles por factura
y romper el modelo. La resolución por artículo sigue llamándose (se usa
para el semáforo y deja rastro en `mappings_articulos`), pero el DAT usa
la cuenta de ventas por defecto. Se confirma en Fase 5 contra una factura
conocida de COLVET — si el contable pide per-artículo, se revisa en v1.1.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from app.mapping.resolver import (
    ClienteSinSubcuentaError,
    ResolucionArticulo,
    Resolver,
)
from app.mapping.store import validar_subcuenta_ingreso
from app.sources.base import Factura

log = logging.getLogger(__name__)

TOLERANCIA_CUADRE = Decimal('0.02')
CUANTIZACION = Decimal('0.01')


class TipoRegistro(str, Enum):
    CABECERA = '1'
    DETALLE = '9'


class OrdenDetalle(str, Enum):
    INTERMEDIO = 'M'
    ULTIMO = 'U'


class OrdenCabecera(str, Enum):
    INICIAL = 'I'


@dataclass
class RegistroCabecera:
    cod_empresa: int
    fecha: str                        # AAAAMMDD
    tipreg: TipoRegistro
    cuenta: str                       # subcuenta cliente 430XXX
    descuenta: str                    # nombre cliente
    numfac: str                       # serie+numero
    orden: OrdenCabecera
    desfac: str                       # descripción del apunte
    importe: Decimal                  # TOTCONIVA


@dataclass
class RegistroDetalle:
    cod_empresa: int
    fecha: str
    tipreg: TipoRegistro
    cuenta: str                       # subcuenta ingreso 700XXX/755XXX
    descuenta: str
    numfac: str
    orden: OrdenDetalle
    descrip: str
    base: Decimal
    por_iva: Decimal
    cuo_iva: Decimal
    por_rec: Decimal
    cuo_rec: Decimal
    por_ret: Decimal
    cuo_ret: Decimal


@dataclass
class ResultadoConstruccion:
    """Cabecera + detalles de una factura más el rastro del semáforo.

    `tipos_resolucion` contiene un entry por LINEA de factura con el tipo
    devuelto por el resolver — Fase 4 lo usa para clasificar verde/amarillo.
    """
    cabecera: RegistroCabecera
    detalles: list[RegistroDetalle]
    tipos_resolucion: list[ResolucionArticulo] = field(default_factory=list)


class FacturaYaExportadaError(ValueError):
    """La factura ya está registrada en la tabla `exportaciones_detalle`."""


class CuadreError(ValueError):
    """sum(bases) + sum(cuotas) no cuadra con TOTCONIVA dentro de la tolerancia."""


# Re-exportar para que callers externos (routes, tests) solo importen de builder
__all__ = [
    'TipoRegistro', 'OrdenCabecera', 'OrdenDetalle',
    'RegistroCabecera', 'RegistroDetalle', 'ResultadoConstruccion',
    'Builder',
    'FacturaYaExportadaError', 'CuadreError', 'ClienteSinSubcuentaError',
    'TOLERANCIA_CUADRE',
]


class Builder:
    """Construye registros SUENLACE para una factura.

    Las dependencias (conexión, resolver, config) se inyectan en __init__.
    `construir_registros` es idempotente sobre la BD salvo por el side-effect
    del resolver (upsert de mappings pendientes), pero NO escribe nada en
    `exportaciones_detalle` — eso lo hace el caller cuando el DAT se ha
    generado y validado.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        resolver: Resolver,
        cod_empresa: int,
        cuenta_ventas_def: str,
        cuadre_tolerancia: Decimal = TOLERANCIA_CUADRE,
    ) -> None:
        """Construye un Builder listo para producir registros SUENLACE.

        `cuadre_tolerancia` — margen (en euros) para el check
        `sum(bases+cuotas) ≈ TOTCONIVA`. El default 0,02€ viene del plan
        y es apropiado para GESDAI real (bases con 2 decimales). Se deja
        como parámetro para tests de integración contra dev data que pueda
        tener redondeos más groseros — nunca subir en producción.
        """
        if not (1 <= cod_empresa <= 99999):
            raise ValueError(
                f"cod_empresa fuera de rango a3ASESOR (1–99999): {cod_empresa}"
            )
        validar_subcuenta_ingreso(cuenta_ventas_def)
        self.conn = conn
        self.resolver = resolver
        self.cod_empresa = cod_empresa
        self.cuenta_ventas_def = cuenta_ventas_def
        self.cuadre_tolerancia = cuadre_tolerancia

    # ─── API pública ────────────────────────────────────────────────────────

    def construir_registros(self, factura: Factura) -> ResultadoConstruccion:
        """Devuelve cabecera + detalles para una factura.

        No escribe fichero ni `exportaciones_detalle`. Las excepciones son
        deliberadas: cualquiera aborta la construcción de ESTA factura, el
        caller decide si ignora o propaga.
        """
        self._validar_no_exportada(factura)
        cliente = self.resolver.resolver_cliente(factura.cliente_codigo)
        self._validar_cuadre(factura)

        # Side-effect: resolver cada línea para dejar rastro en mappings_articulos.
        # No alimenta los detalles — en v1.0 todos usan cuenta_ventas_def.
        tipos_resolucion = [
            self.resolver.resolver_articulo(linea.articulo)
            for linea in factura.lineas
        ]

        fecha_str = factura.fecha.strftime('%Y%m%d')
        numfac = f"{factura.serie.strip()}{factura.numero.strip()}"

        cabecera = RegistroCabecera(
            cod_empresa=self.cod_empresa,
            fecha=fecha_str,
            tipreg=TipoRegistro.CABECERA,
            cuenta=cliente.subcuenta_a3,
            descuenta=cliente.nombre,
            numfac=numfac,
            orden=OrdenCabecera.INICIAL,
            desfac=f"Fra {numfac}",
            importe=_q(factura.total_con_iva),
        )

        detalles = self._construir_detalles(factura, fecha_str, numfac)

        return ResultadoConstruccion(
            cabecera=cabecera,
            detalles=detalles,
            tipos_resolucion=tipos_resolucion,
        )

    # ─── Construcción de detalles ───────────────────────────────────────────

    def _construir_detalles(
        self,
        factura: Factura,
        fecha_str: str,
        numfac: str,
    ) -> list[RegistroDetalle]:
        """Emite un detalle por cada (PTSBASEn, IVAn, RECEQUIn) con base != 0.

        El último detalle lleva `orden='U'`, los anteriores `'M'`. Si la
        factura no tiene NINGUNA base distinta de cero, devuelve lista vacía
        y el cuadre habrá avisado antes.

        Las bases NEGATIVAS son legítimas: COLVET emite ocasionalmente
        "rectificativas informales" como ingresos en negativo en lugar de
        seguir el flujo formal de factura rectificativa. Filtrar solo `> 0`
        descartaría esos tramos y produciría un DAT corrupto (cabecera sin
        detalles) sin avisar.
        """
        tramos = [
            (factura.ptsbase1, factura.iva1, factura.recequi1),
            (factura.ptsbase2, factura.iva2, factura.recequi2),
            (factura.ptsbase3, factura.iva3, factura.recequi3),
        ]
        activos = [(base, iva, rec) for base, iva, rec in tramos if base != 0]
        if not activos:
            return []

        retirpf = factura.retirpf
        detalles: list[RegistroDetalle] = []
        for idx, (base, iva, rec) in enumerate(activos):
            es_ultimo = idx == len(activos) - 1
            cuo_iva = _q(base * iva / 100)
            cuo_rec = _q(base * rec / 100)
            cuo_ret = _q(base * retirpf / 100)
            detalles.append(
                RegistroDetalle(
                    cod_empresa=self.cod_empresa,
                    fecha=fecha_str,
                    tipreg=TipoRegistro.DETALLE,
                    cuenta=self.cuenta_ventas_def,
                    descuenta=f"Ventas {iva}%",
                    numfac=numfac,
                    orden=(
                        OrdenDetalle.ULTIMO if es_ultimo else OrdenDetalle.INTERMEDIO
                    ),
                    descrip=f"Fra {numfac}",
                    base=_q(base),
                    por_iva=_q(iva),
                    cuo_iva=cuo_iva,
                    por_rec=_q(rec),
                    cuo_rec=cuo_rec,
                    por_ret=_q(retirpf),
                    cuo_ret=cuo_ret,
                )
            )
        return detalles

    # ─── Validaciones ───────────────────────────────────────────────────────

    def _validar_cuadre(self, factura: Factura) -> None:
        """Verifica que sum(bases)+sum(cuotas)−retención ≈ TOTCONIVA.

        Fórmula exacta (Sección 8 Fase 3 del plan):

            calculado = PTSBASE1+PTSBASE2+PTSBASE3
                      + (PTSBASE1*IVA1 + PTSBASE2*IVA2 + PTSBASE3*IVA3) / 100
                      + (PTSBASE1*RECEQUI1 + ... ) / 100
                      − (PTSBASE1+PTSBASE2+PTSBASE3) * RETIRPF / 100

        |calculado − TOTCONIVA| debe ser ≤ `self.cuadre_tolerancia`.

        Nota sobre RETIRPF: asumimos que `TOTCONIVA` en GESDAI es POST-retención
        (es decir, el importe neto facturado). Si en la validación con datos
        reales de COLVET (Fase 5) las facturas con retención IRPF fallan cuadre
        sistemáticamente por la magnitud exacta de la retención, habrá que
        invertir el signo aquí. Documentado en CLAUDE.md sección "Contexto de
        dominio" para revisión futura.
        """
        bases_total = factura.ptsbase1 + factura.ptsbase2 + factura.ptsbase3
        cuotas_iva = (
            factura.ptsbase1 * factura.iva1
            + factura.ptsbase2 * factura.iva2
            + factura.ptsbase3 * factura.iva3
        ) / 100
        cuotas_rec = (
            factura.ptsbase1 * factura.recequi1
            + factura.ptsbase2 * factura.recequi2
            + factura.ptsbase3 * factura.recequi3
        ) / 100
        retencion = bases_total * factura.retirpf / 100

        calculado = bases_total + cuotas_iva + cuotas_rec - retencion
        diff = abs(calculado - factura.total_con_iva)
        if diff > self.cuadre_tolerancia:
            raise CuadreError(
                f"Factura {factura.codigo}: cuadre fuera de tolerancia "
                f"({self.cuadre_tolerancia}€). Calculado={calculado}, "
                f"TOTCONIVA={factura.total_con_iva}, diff={diff}"
            )

    def _validar_no_exportada(self, factura: Factura) -> None:
        """Evita que una factura entre dos veces al flujo contable.

        Fuente de verdad: la tabla `exportaciones_detalle`. Nunca se lee
        `cfactura.CONTABIL` (Decisión D01 del plan — CONTABIL es solo
        aviso informativo).
        """
        fila = self.conn.execute(
            "SELECT 1 FROM exportaciones_detalle WHERE codigo_factura = ? LIMIT 1",
            (factura.codigo,),
        ).fetchone()
        if fila is not None:
            raise FacturaYaExportadaError(
                f"Factura {factura.codigo} ya está registrada en una "
                f"exportación anterior — no se puede incluir de nuevo"
            )


def _q(valor: Decimal) -> Decimal:
    """Cuantiza a 2 decimales con redondeo banker-friendly (HALF_UP)."""
    return Decimal(valor).quantize(CUANTIZACION, rounding=ROUND_HALF_UP)
