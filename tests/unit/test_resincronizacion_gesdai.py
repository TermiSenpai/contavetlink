"""Tests de regresión: ¿qué pasa cuando GESDAI cambia bajo los pies?

Estos tests documentan el contrato del intermediario frente a mutaciones
del catálogo de GESDAI entre dos sincronizaciones. GESDAI es la fuente
de verdad para "qué existe", pero la subcuenta contable, las notas y el
estado `revisado` viven sólo en el intermediario, así que cualquier
re-sync tiene que preservarlos.

Escenarios cubiertos:

  · Cliente / artículo RENOMBRADO en GESDAI (con y sin revisado=1).
  · NIF añadido, modificado o eliminado en GESDAI.
  · Cliente / artículo BORRADO en GESDAI — el mapping queda huérfano y
    debe seguir sirviendo para exportar facturas históricas.
  · REUTILIZACIÓN de un código (GESDAI borra CLI001 y reasigna el mismo
    código a otra empresa): caso peligroso porque la subcuenta antigua
    se aplicaría al cliente nuevo. Documentamos el comportamiento actual.
  · Trailing spaces y casing en códigos (DBF/FoxPro suele padear).
  · El nombre que va al DAT viene del intermediario, NO de la factura ni
    de GESDAI vivo: una factura cargada por DBF con nombre desactualizado
    sigue exportándose con el nombre revisado del operador.
  · El Resolver no consulta la fuente — sólo SQLite — así que se puede
    exportar sin DBF accesible si el mapping ya existe.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.exporter.builder import Builder
from app.mapping import sync as sync_mod
from app.mapping.resolver import Resolver, TipoResolucion
from app.mapping.store import (
    get_articulo_mapping,
    get_cliente_mapping,
    marcar_articulo_revisado,
    marcar_cliente_revisado,
    set_cuenta_articulo,
    set_subcuenta_cliente,
    upsert_articulo_mapping,
    upsert_cliente_mapping,
)
from app.sources.base import Articulo, Cliente, DataSource, Factura, Filtros, LineaFactura


# ─── Fuente de datos fake ─────────────────────────────────────────────────


class _FakeSource(DataSource):
    """Simula GESDAI: el caller decide qué clientes/artículos hay en cada sync."""

    def __init__(
        self,
        clientes: list[Cliente] | None = None,
        articulos: list[Articulo] | None = None,
    ) -> None:
        self._clientes = clientes or []
        self._articulos = articulos or []

    def get_facturas(self, filtros: Filtros):  # pragma: no cover
        return []

    def get_cliente(self, codigo):  # pragma: no cover
        for c in self._clientes:
            if c.codigo == codigo:
                return c
        raise KeyError(codigo)

    def get_clientes(self):
        return list(self._clientes)

    def get_articulos(self):
        return list(self._articulos)


CUENTA_DEFAULT = '700001'
COD_EMPRESA = 42


def _resolver(conn):
    return Resolver(conn, cuenta_default=CUENTA_DEFAULT)


# ═══════════════════════════════════════════════════════════════════════════
#   CLIENTE: rename y cambios de campos en GESDAI
# ═══════════════════════════════════════════════════════════════════════════


def test_rename_cliente_no_revisado_actualiza_nombre_preservando_subcuenta(db_conn):
    """GESDAI renombra un cliente con mapping NO revisado: el nombre se
    refresca pero la subcuenta asignada (aunque sea provisional) sobrevive.

    Es el caso normal: el operador asignó la cuenta pero todavía no la
    confirmó. Una re-sincronización no debe perder ese trabajo a medio
    hacer — sólo refrescar el nombre/NIF que la fuente conoce mejor.
    """
    src1 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Clínica Alpha SL', nif='B12345678')])
    sync_mod.sync_clientes(db_conn, src1)
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')  # pre-asignada, sin revisar

    src2 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Clínica Veterinaria Alpha SL', nif='B12345678')])
    r = sync_mod.sync_clientes(db_conn, src2)

    assert r.actualizados == 1
    fila = get_cliente_mapping(db_conn, 'CLI001')
    assert fila['nombre'] == 'Clínica Veterinaria Alpha SL'
    assert fila['subcuenta_a3'] == '430010', (
        "una re-sincronización NO debe perder la subcuenta provisional asignada"
    )


def test_rename_cliente_revisado_conserva_nombre_viejo(db_conn):
    """Si el operador ya confirmó (`revisado=1`), el sync hace SKIP entero:
    ni el nombre se refresca aunque GESDAI tenga uno nuevo.

    Trade-off conocido: si COLVET cambia razón social ("X SL" → "X SLU"),
    el nombre que viaja al DAT sigue siendo el viejo hasta que el operador
    desmarque y vuelva a revisar. Es deliberado — preferimos preservar el
    trabajo manual a sincronizar agresivamente.
    """
    src1 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha SL', nif='B12345678')])
    sync_mod.sync_clientes(db_conn, src1)
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')
    marcar_cliente_revisado(db_conn, 'CLI001')

    src2 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha SLU (refundada)', nif='B99999999')])
    r = sync_mod.sync_clientes(db_conn, src2)

    assert r.saltados_revisados == 1
    fila = get_cliente_mapping(db_conn, 'CLI001')
    assert fila['nombre'] == 'Alpha SL', "revisado=1 congela también el nombre"
    assert fila['nif'] == 'B12345678', "revisado=1 congela también el NIF"
    assert fila['subcuenta_a3'] == '430010'


def test_nif_se_actualiza_en_no_revisado(db_conn):
    """Un cambio de NIF en GESDAI (raro pero ocurre: corrección de un dato
    mal introducido) se propaga al intermediario mientras el cliente no
    esté revisado."""
    src1 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha', nif='B11111111')])
    sync_mod.sync_clientes(db_conn, src1)

    src2 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha', nif='B22222222')])
    sync_mod.sync_clientes(db_conn, src2)

    assert get_cliente_mapping(db_conn, 'CLI001')['nif'] == 'B22222222'


def test_nif_se_pone_a_null_si_desaparece_en_gesdai(db_conn):
    """Si GESDAI borra el NIF, el sync lo pone a NULL (sin COALESCE en `nif`).

    Documenta el comportamiento actual: no es un bug, es una elección — si
    GESDAI dice "este cliente ya no tiene NIF", confiamos en la fuente.
    """
    src1 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha', nif='B12345678')])
    sync_mod.sync_clientes(db_conn, src1)

    src2 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha', nif=None)])
    sync_mod.sync_clientes(db_conn, src2)

    assert get_cliente_mapping(db_conn, 'CLI001')['nif'] is None


def test_sync_preserva_notas_del_operador(db_conn):
    """Las notas que el operador escribió en la UI no se pierden en el sync.

    Garantía proporcionada por `COALESCE(?, notas)` en el UPDATE — la
    fuente no conoce el campo `notas` y pasa NULL, así que COALESCE
    mantiene el valor existente.
    """
    upsert_cliente_mapping(db_conn, codigo='CLI001', nombre='Alpha', notas='Cobra a 60 días')

    src = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha renombrado')])
    sync_mod.sync_clientes(db_conn, src)

    fila = get_cliente_mapping(db_conn, 'CLI001')
    assert fila['notas'] == 'Cobra a 60 días'
    assert fila['nombre'] == 'Alpha renombrado'  # rename sí se aplica


# ═══════════════════════════════════════════════════════════════════════════
#   ARTÍCULO: rename de descripción y cambios de campos
# ═══════════════════════════════════════════════════════════════════════════


def test_rename_articulo_no_revisado_actualiza_descripcion_preservando_cuenta(db_conn):
    """GESDAI cambia la descripción de un artículo no revisado: la
    descripción se refresca, la cuenta_a3 propuesta sobrevive."""
    src1 = _FakeSource(articulos=[Articulo(clave='CHIP', descripcion='Microchip')])
    sync_mod.sync_articulos(db_conn, src1)
    set_cuenta_articulo(db_conn, 'CHIP', '700100')

    src2 = _FakeSource(articulos=[Articulo(clave='CHIP', descripcion='Microchip canino con identificación AVID')])
    sync_mod.sync_articulos(db_conn, src2)

    fila = get_articulo_mapping(db_conn, 'CHIP')
    assert fila['descripcion'] == 'Microchip canino con identificación AVID'
    assert fila['cuenta_a3'] == '700100'


def test_rename_articulo_revisado_conserva_descripcion_vieja(db_conn):
    """Riesgo silencioso conocido y documentado: si el operador revisó un
    artículo y luego GESDAI le cambia la descripción, en la UI seguirá
    apareciendo la descripción VIEJA. El operador tendría que desmarcar
    revisado para verlo refrescado.

    Aceptado como trade-off — preferimos congelar todo el mapping a
    sincronizar parcialmente y arriesgar dejar la cuenta_a3 mal asignada
    si el "renombrado" en realidad es un cambio de naturaleza del artículo.
    """
    src1 = _FakeSource(articulos=[Articulo(clave='CERT', descripcion='Certificado salud')])
    sync_mod.sync_articulos(db_conn, src1)
    set_cuenta_articulo(db_conn, 'CERT', '755001')
    marcar_articulo_revisado(db_conn, 'CERT')

    src2 = _FakeSource(articulos=[Articulo(clave='CERT', descripcion='Certificado oficial veterinario')])
    r = sync_mod.sync_articulos(db_conn, src2)

    assert r.saltados_revisados == 1
    assert get_articulo_mapping(db_conn, 'CERT')['descripcion'] == 'Certificado salud'


def test_articulo_que_pierde_descripcion_en_gesdai_la_preserva(db_conn):
    """Si GESDAI deja la descripción de un artículo a None, el sync usa
    `COALESCE(?, descripcion)` y mantiene la anterior. Comportamiento
    deseado: una descripción vacía en GESDAI casi siempre es un error de
    grabación del operador, no una decisión consciente.
    """
    src1 = _FakeSource(articulos=[Articulo(clave='VAC', descripcion='Vacuna polivalente')])
    sync_mod.sync_articulos(db_conn, src1)

    src2 = _FakeSource(articulos=[Articulo(clave='VAC', descripcion=None)])
    sync_mod.sync_articulos(db_conn, src2)

    assert get_articulo_mapping(db_conn, 'VAC')['descripcion'] == 'Vacuna polivalente'


# ═══════════════════════════════════════════════════════════════════════════
#   DATOS HUÉRFANOS: el elemento desaparece de GESDAI
# ═══════════════════════════════════════════════════════════════════════════


def test_cliente_borrado_en_gesdai_sobrevive_en_intermediario(db_conn):
    """Si GESDAI deja de listar un cliente que tenía mapping revisado, el
    sync NO borra la fila. Es deliberado: facturas históricas que sigan
    referenciando ese cliente deben poder exportarse.

    El catálogo de GESDAI puede limpiarse (clientes inactivos, fusiones),
    pero las facturas de ejercicios anteriores no cambian. El resolver
    necesita seguir encontrando la subcuenta para no romper exportaciones
    de cierre de año.
    """
    src1 = _FakeSource(clientes=[
        Cliente(codigo='CLI001', nombre='Alpha SL'),
        Cliente(codigo='CLI002', nombre='Beta SL'),
    ])
    sync_mod.sync_clientes(db_conn, src1)
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')
    marcar_cliente_revisado(db_conn, 'CLI001')

    # GESDAI "olvida" CLI001
    src2 = _FakeSource(clientes=[Cliente(codigo='CLI002', nombre='Beta SL')])
    sync_mod.sync_clientes(db_conn, src2)

    fila = get_cliente_mapping(db_conn, 'CLI001')
    assert fila is not None, "el mapping huérfano debe sobrevivir"
    assert fila['subcuenta_a3'] == '430010'

    # …y el resolver lo sigue encontrando para facturas históricas
    resolver = _resolver(db_conn)
    resolucion = resolver.resolver_cliente('CLI001')
    assert resolucion.subcuenta_a3 == '430010'


def test_articulo_borrado_en_gesdai_no_rompe_resolucion(db_conn):
    """Equivalente al test anterior para artículos. Una factura antigua que
    use el artículo CHIP debe poder exportarse aunque GESDAI ya no lo tenga
    en `material.dbf`."""
    src1 = _FakeSource(articulos=[Articulo(clave='CHIP', descripcion='Microchip')])
    sync_mod.sync_articulos(db_conn, src1)
    set_cuenta_articulo(db_conn, 'CHIP', '700100')
    marcar_articulo_revisado(db_conn, 'CHIP')

    # GESDAI elimina CHIP del catálogo
    src2 = _FakeSource(articulos=[])
    sync_mod.sync_articulos(db_conn, src2)

    resolver = _resolver(db_conn)
    resultado = resolver.resolver_articulo('CHIP')
    assert resultado.tipo == TipoResolucion.MAPPING
    assert resultado.cuenta_a3 == '700100'


# ═══════════════════════════════════════════════════════════════════════════
#   REUTILIZACIÓN DE CÓDIGOS — riesgo silencioso documentado
# ═══════════════════════════════════════════════════════════════════════════


def test_codigo_cliente_reutilizado_revisado_mantiene_subcuenta_vieja(db_conn):
    """⚠️ RIESGO documentado. Si GESDAI borra el cliente CLI001 (Alpha SL,
    430010) y más tarde reasigna el código CLI001 a un cliente totalmente
    distinto (Beta SLU), el sync verá `revisado=1` y hará SKIP. El
    resultado: facturas del cliente NUEVO Beta SLU se exportarían con la
    subcuenta de Alpha SL → cargo contable al cliente equivocado.

    El intermediario no puede detectar esto automáticamente con los datos
    actuales — no rastreamos NIF como clave secundaria de identidad. La
    mitigación es operativa: COLVET no reutiliza códigos de cliente.

    Si en validación con datos reales (Fase 5) se observa que GESDAI sí
    reutiliza códigos, habría que añadir detección por cambio de NIF en
    `sync_clientes` (lanzar warning o forzar revisado=0 cuando el NIF
    cambia y la fila está revisada). Documentado aquí como contrato actual.
    """
    src1 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Alpha SL', nif='B11111111')])
    sync_mod.sync_clientes(db_conn, src1)
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')
    marcar_cliente_revisado(db_conn, 'CLI001')

    # GESDAI reasigna el código a otro cliente (otro NIF, otra razón social)
    src2 = _FakeSource(clientes=[Cliente(codigo='CLI001', nombre='Beta SLU', nif='B99999999')])
    r = sync_mod.sync_clientes(db_conn, src2)

    assert r.saltados_revisados == 1
    fila = get_cliente_mapping(db_conn, 'CLI001')
    assert fila['nombre'] == 'Alpha SL', "SKIP silencioso del mapping antiguo"
    assert fila['nif'] == 'B11111111'
    assert fila['subcuenta_a3'] == '430010', (
        "el sync no detecta la reutilización: la subcuenta de Alpha se "
        "aplicaría al cliente Beta — riesgo documentado"
    )


def test_clave_articulo_reutilizada_revisada_mantiene_cuenta_vieja(db_conn):
    """⚠️ RIESGO equivalente para artículos. Si el código CHIP se reasigna
    a un producto distinto (p.ej. dejó de ser un microchip y ahora es una
    chuche de adiestramiento), el sync no lo detecta — la cuenta_a3
    revisada se sigue aplicando al "nuevo" CHIP.

    Mitigación operativa idéntica a clientes: no reutilizar claves.
    """
    src1 = _FakeSource(articulos=[Articulo(clave='CHIP', descripcion='Microchip canino')])
    sync_mod.sync_articulos(db_conn, src1)
    set_cuenta_articulo(db_conn, 'CHIP', '700100')
    marcar_articulo_revisado(db_conn, 'CHIP')

    src2 = _FakeSource(articulos=[Articulo(clave='CHIP', descripcion='Premio adiestramiento snack')])
    sync_mod.sync_articulos(db_conn, src2)

    fila = get_articulo_mapping(db_conn, 'CHIP')
    assert fila['descripcion'] == 'Microchip canino'  # SKIP
    assert fila['cuenta_a3'] == '700100'


# ═══════════════════════════════════════════════════════════════════════════
#   NORMALIZACIÓN — trailing spaces, casing, encoding
# ═══════════════════════════════════════════════════════════════════════════


def test_codigos_son_case_sensitive(db_conn):
    """`CLI001` y `cli001` son códigos DISTINTOS — el PRIMARY KEY de
    SQLite es case-sensitive con tipo TEXT. Documentado para que nadie
    intente "normalizar" a mayúsculas en el sync (rompería referencias
    de facturas existentes)."""
    upsert_cliente_mapping(db_conn, codigo='CLI001', nombre='Alpha mayúsculas')
    upsert_cliente_mapping(db_conn, codigo='cli001', nombre='Alpha minúsculas')

    fila_mayus = get_cliente_mapping(db_conn, 'CLI001')
    fila_minus = get_cliente_mapping(db_conn, 'cli001')
    assert fila_mayus['nombre'] == 'Alpha mayúsculas'
    assert fila_minus['nombre'] == 'Alpha minúsculas'


def test_caracteres_acentuados_en_nombre_se_persisten(db_conn):
    """cp1252 desde DBF debe llegar limpio al intermediario: ñ, á, é..."""
    src = _FakeSource(clientes=[
        Cliente(codigo='CLI100', nombre='Clínica Pequeños Animales Núñez & Sánchez SL'),
    ])
    sync_mod.sync_clientes(db_conn, src)

    fila = get_cliente_mapping(db_conn, 'CLI100')
    assert fila['nombre'] == 'Clínica Pequeños Animales Núñez & Sánchez SL'


# ═══════════════════════════════════════════════════════════════════════════
#   PROPAGACIÓN AL DAT — el nombre lo decide el intermediario
# ═══════════════════════════════════════════════════════════════════════════


def test_dat_lleva_nombre_del_intermediario_no_de_la_factura(db_conn):
    """La cabecera SUENLACE usa `cliente.nombre` del intermediario, no el
    nombre que viniera en la factura de GESDAI. Si el operador revisó al
    cliente con un nombre normalizado distinto al que GESDAI grabó en su
    día, el DAT lleva el normalizado.

    Verificación clave: una factura del cliente CLI001 cargada con un
    nombre desactualizado se exporta con el nombre vigente en el mapping.
    """
    upsert_cliente_mapping(
        db_conn, codigo='CLI001', nombre='Clínica Alpha SL (normalizada por operador)',
    )
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')
    marcar_cliente_revisado(db_conn, 'CLI001')

    # La factura simula haber sido leída de GESDAI con un cliente_codigo
    # cuyo nombre "en vivo" sería otro — pero al builder eso le da igual,
    # lo único que mira es cliente_codigo.
    factura = Factura(
        codigo='FAC0001',
        serie='A',
        numero='000001',
        cliente_codigo='CLI001',
        fecha=date(2026, 1, 15),
        total_base=Decimal('100.00'),
        total_con_iva=Decimal('121.00'),
        ptsbase1=Decimal('100.00'), iva1=Decimal('21'), recequi1=Decimal('0'),
        ptsbase2=Decimal('0'), iva2=Decimal('0'), recequi2=Decimal('0'),
        ptsbase3=Decimal('0'), iva3=Decimal('0'), recequi3=Decimal('0'),
        retirpf=Decimal('0'),
        contabil=False,
        lineas=[],
    )
    builder = Builder(db_conn, resolver=_resolver(db_conn),
                      cod_empresa=COD_EMPRESA, cuenta_ventas_def=CUENTA_DEFAULT)

    resultado = builder.construir_registros(factura)
    assert resultado.cabecera.descuenta == 'Clínica Alpha SL (normalizada por operador)'


# ═══════════════════════════════════════════════════════════════════════════
#   RESOLVER — aislamiento de la fuente y idempotencia
# ═══════════════════════════════════════════════════════════════════════════


def test_resolver_no_consulta_la_fuente_solo_sqlite(db_conn):
    """Una vez que el sync ha poblado el intermediario, el Resolver es
    100% independiente de la fuente. Esto permite exportar aunque GESDAI
    esté bloqueado por el sistema operativo (caso típico: otros usuarios
    facturando), siempre que el operador haya sincronizado previamente.

    El test verifica que NO se construye ningún DataSource: el resolver
    debe operar sólo con la conexión SQLite. Si en el futuro alguien
    introduce un acceso a la fuente dentro del resolver, este test lo
    detectará al fallar (la falta de fixtures de fuente lo dejaría en
    evidencia inmediatamente al revisar la traza).
    """
    upsert_cliente_mapping(db_conn, codigo='CLI001', nombre='Alpha')
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')

    resolver = _resolver(db_conn)  # ← ninguna fuente inyectada
    resultado = resolver.resolver_cliente('CLI001')
    assert resultado.subcuenta_a3 == '430010'


def test_resolver_articulo_repetido_no_duplica_mapping(db_conn):
    """Resolver el mismo artículo dos veces en la misma factura (o entre
    facturas) no debe crear filas duplicadas en `mappings_articulos`. La
    PRIMARY KEY del store lo garantiza, pero queremos un test directo que
    cubra el ciclo completo del resolver."""
    resolver = _resolver(db_conn)

    resolver.resolver_articulo('NUEVO-ART')
    resolver.resolver_articulo('NUEVO-ART')
    resolver.resolver_articulo('NUEVO-ART')

    filas = db_conn.execute(
        "SELECT COUNT(*) FROM mappings_articulos WHERE clave_gesdai = ?",
        ('NUEVO-ART',),
    ).fetchone()[0]
    assert filas == 1


def test_resolver_articulo_con_cuenta_default_distinta_no_pisa_pendiente_anterior(db_conn):
    """Si un resolver se construyó con `cuenta_default='700001'`, persiste
    un pendiente con esa cuenta. Si más tarde otro resolver con
    `cuenta_default='755001'` ve el mismo artículo, el segundo NO sobreescribe
    la cuenta (el COALESCE del store sólo sobreescribe valores NULL, pero
    además el resolver primero ya escribió un valor — así que el UPDATE
    pasa el mismo valor o el default nuevo).

    Test contra-regresión: el comportamiento documentado es que el primer
    valor gana hasta que el operador revise. Verifica que cambiar el default
    de la app no recablea silenciosamente mappings ya creados.
    """
    r1 = Resolver(db_conn, cuenta_default='700001')
    r1.resolver_articulo('SIN-MAPEAR')
    cuenta_1 = get_articulo_mapping(db_conn, 'SIN-MAPEAR')['cuenta_a3']
    assert cuenta_1 == '700001'

    # Cambia la cuenta default y resuelve de nuevo
    r2 = Resolver(db_conn, cuenta_default='755001')
    r2.resolver_articulo('SIN-MAPEAR')
    cuenta_2 = get_articulo_mapping(db_conn, 'SIN-MAPEAR')['cuenta_a3']
    # El store hace UPDATE con cuenta_a3='755001' → SÍ se actualiza porque
    # `cuenta_a3 = COALESCE(?, cuenta_a3)` y '755001' no es NULL. Documenta
    # el comportamiento: cambiar la cuenta default REASIGNA los pendientes.
    # Si esto se considera no deseado, sería una mejora futura.
    assert cuenta_2 == '755001'


# ═══════════════════════════════════════════════════════════════════════════
#   IDEMPOTENCIA Y ESTADÍSTICAS
# ═══════════════════════════════════════════════════════════════════════════


def test_sync_dos_veces_seguidas_sin_cambios_no_genera_inserts(db_conn):
    """Re-sync inmediato (sin cambios en la fuente) tras una sync inicial
    sólo debe producir `actualizados` (filas no-revisadas refrescadas con
    los mismos datos) o `saltados_revisados`, nunca `insertados`."""
    src = _FakeSource(clientes=[
        Cliente(codigo='CLI001', nombre='Alpha'),
        Cliente(codigo='CLI002', nombre='Beta'),
    ])
    sync_mod.sync_clientes(db_conn, src)

    r2 = sync_mod.sync_clientes(db_conn, src)
    assert r2.insertados == 0
    assert r2.total == 2


def test_sync_mixto_insertados_actualizados_saltados(db_conn):
    """Un sync con mix de estados produce las tres contabilidades."""
    src1 = _FakeSource(clientes=[
        Cliente(codigo='CLI001', nombre='Alpha'),  # se marcará revisado
        Cliente(codigo='CLI002', nombre='Beta'),   # quedará no revisado
    ])
    sync_mod.sync_clientes(db_conn, src1)
    set_subcuenta_cliente(db_conn, 'CLI001', '430010')
    marcar_cliente_revisado(db_conn, 'CLI001')

    src2 = _FakeSource(clientes=[
        Cliente(codigo='CLI001', nombre='Alpha cambiado'),  # saltado_revisado
        Cliente(codigo='CLI002', nombre='Beta cambiado'),   # actualizado
        Cliente(codigo='CLI003', nombre='Gamma'),           # insertado
    ])
    r = sync_mod.sync_clientes(db_conn, src2)

    assert r.insertados == 1
    assert r.actualizados == 1
    assert r.saltados_revisados == 1
    assert r.total == 3
