# Plan de Desarrollo — Exportador GESDAI → a3ASESOR
**Proyecto:** `gesdai-exporter`  
**Versión del plan:** 1.3  
**Fecha:** Abril 2026  
**Autor:** Xkoi Studio  

---

## Índice

1. [Visión general](#1-visión-general)
2. [Prerequisitos — antes de escribir código](#2-prerequisitos--antes-de-escribir-código)
3. [Principios de arquitectura y escalabilidad](#3-principios-de-arquitectura-y-escalabilidad)
4. [Stack tecnológico](#4-stack-tecnológico)
5. [Estructura del repositorio](#5-estructura-del-repositorio)
6. [Modelo de datos](#6-modelo-de-datos)
7. [Especificación SUENLACE.DAT](#7-especificación-suenlacedat)
8. [Fases de desarrollo](#8-fases-de-desarrollo)
9. [Plan de tests](#9-plan-de-tests)
10. [Distribución y despliegue](#10-distribución-y-despliegue)
11. [Sistema de actualizaciones](#11-sistema-de-actualizaciones)
12. [Seguridad y protección de datos](#12-seguridad-y-protección-de-datos)
13. [Criterios de aceptación por fase](#13-criterios-de-aceptación-por-fase)
14. [Riesgos y mitigaciones](#14-riesgos-y-mitigaciones)
15. [Hoja de ruta post-producción](#15-hoja-de-ruta-post-producción)
16. [Apéndice — Decisiones de diseño](#16-apéndice--decisiones-de-diseño)

---

## 1. Visión general

### Problema
COLVET Guadalajara usa GESDAI para facturar y a3ASESOR para contabilidad. Los asientos contables de cada factura se introducen hoy a mano, mes a mes. Eso es tiempo y riesgo de error.

### Solución
Una herramienta local que lee las facturas de GESDAI, las convierte al formato que entiende a3ASESOR (`SUENLACE.DAT`) y las deja listas para importar. Como los códigos de cliente y artículo de GESDAI no tienen equivalente directo en a3ASESOR, incluye una interfaz web donde se revisa y gestiona ese mapeo, con filtrado avanzado y posibilidad de automatización progresiva.

En vez de introducir asientos a mano, cada mes: abrir la herramienta → seleccionar rango y filtros → revisar el semáforo → generar el DAT → importar en a3ASESOR.

### Principios de diseño
- **GESDAI nunca se modifica** — acceso estrictamente de solo lectura
- **El intermediario es auditable** — todo mapping es visible y editable
- **Fallar de forma controlada** — si un dato no se puede resolver, se marca; nunca se omite en silencio
- **Trazabilidad total** — cada DAT generado queda registrado con fecha, rango, hash y versión
- **Arquitectura abierta** — diseñada para crecer: nuevas fuentes de datos, más usuarios, servidor

### Restricciones conocidas del sistema contable

a3ASESOR usa subcuentas de **6 dígitos** en el plan de cuentas de COLVET. En SUENLACE el campo `cuenta` tiene 12 caracteres: las subcuentas se paddean con espacios a la derecha.

| Tipo | Formato | En SUENLACE (12 chars) |
|---|---|---|
| Clientes | `430XXX` (430001–430999) | `430001      ` |
| Ventas generales | `700XXX` | `700001      ` |
| Ingresos diversos | `755XXX` | `755001      ` |

Con 552 clientes activos en GESDAI el rango 430001–430999 tiene margen suficiente.

---

## 2. Prerequisitos — antes de escribir código

### 2.1 Acceso a datos ✅ Sin restricción adicional

Esta es una herramienta interna de COLVET desarrollada por personal interno. No aplica la figura de encargado externo del tratamiento (art. 28 RGPD). El acceso a los datos de producción está implícitamente autorizado en el contexto del puesto.

El repositorio GitHub debe ser **privado** como buena práctica de seguridad del código fuente.

### 2.2 Técnico — formato SUENLACE ✅ Resuelto

El fichero `SUENLACE.XLS` encontrado en la instalación de a3ASESOR contiene la especificación oficial completa. Está documentado en la **Sección 7**.

Queda confirmar con Anguix un único dato antes de la Fase 3:

- **Código de empresa** (`se-ci-codemp`): el número de COLVET en a3ASESOR (1–99999)

El formato numérico de importes se confirma empíricamente en la Fase 5 (paso 7) mediante una exportación de prueba con importe conocido.

### 2.3 Carga inicial de mappings

Con 552 clientes, la carga manual uno a uno es inviable. Hay que preparar un **CSV de carga inicial** cruzando los clientes de GESDAI con el plan de cuentas de a3ASESOR. La herramienta incluye importación masiva desde CSV y Excel en **v1.0**.

---

## 3. Principios de arquitectura y escalabilidad

Esta sección define las decisiones de diseño que garantizan que la herramienta pueda crecer sin reescribirse.

### 3.1 Capa de fuentes de datos (`sources/`)

El módulo de lectura de datos **no es específico de GESDAI**. Toda fuente de datos implementa la misma interfaz abstracta:

```python
# sources/base.py
class DataSource:
    def get_facturas(self, filtros: Filtros) -> list[Factura]: ...
    def get_cliente(self, codigo: str) -> Cliente: ...
    def get_articulos(self) -> list[Articulo]: ...
    def get_clientes(self) -> list[Cliente]: ...
```

Implementaciones actuales y futuras:

```
sources/
├── base.py          # Interfaz abstracta + modelos de datos comunes
├── dbf_source.py    # ← v1.0: lee GESDAI (DBF/FoxPro)
├── excel_source.py  # ← futuro: lee facturas desde Excel
└── csv_source.py    # ← futuro: lee facturas desde CSV
```

El `builder.py`, el `resolver.py` y toda la lógica de negocio trabajan con los modelos de `base.py`. Nunca importan nada de `dbf_source.py` directamente. Añadir una fuente nueva en el futuro no requiere tocar ningún otro módulo.

### 3.2 Filtrado avanzado con AND / OR

El panel de exportación permite componer filtros de forma intuitiva. Los filtros se representan internamente como un árbol de condiciones:

```python
# Ejemplo: facturas de enero 2026 del cliente CLI00001 O CLI00002
Filtros(
    operador=AND,
    condiciones=[
        Condicion("fecha", ENTRE, ("2026-01-01", "2026-01-31")),
        Filtros(
            operador=OR,
            condiciones=[
                Condicion("cliente", IGUAL, "CLI00001"),
                Condicion("cliente", IGUAL, "CLI00002"),
            ]
        )
    ]
)
```

La UI ofrece un constructor de filtros visual (sin drag-and-drop por ahora): grupos de condiciones con botón "+ Condición" y selector AND/OR entre grupos. No es un query builder de base de datos expuesto al usuario — es una selección guiada por campos conocidos (fecha, cliente, serie, estado de resolución, importe).

Campos filtrables en v1.0:

| Campo | Operadores |
|---|---|
| Fecha de factura | entre, antes de, después de |
| Cliente | es, no es, contiene |
| Serie | es, no es |
| Estado de resolución | verde / amarillo / rojo / gris |
| Importe total | mayor que, menor que, entre |

### 3.3 Arquitectura local → servidor

Flask ya es un servidor web. La herramienta está diseñada para que en el futuro pueda desplegarse en red sin cambios de arquitectura:

- Los templates y JS usan **URLs relativas** — nunca `localhost` hardcodeado
- La configuración usa rutas configurables — nunca `C:\GESDAI\` hardcodeado
- El SQLite está en una ruta configurable (`%APPDATA%` por defecto en local)
- No hay estado de sesión en memoria — todo persiste en SQLite
- La autenticación no está implementada en v1.0 pero la estructura la permite (Blueprint `auth/` reservado)

### 3.4 Múltiples fuentes por cliente

En el futuro, el mismo cliente puede tener facturas de GESDAI **y** de un Excel externo. El modelo de datos lo soporta mediante el campo `fuente` en la tabla de exportaciones:

```sql
-- exportaciones_detalle ya incluye el campo fuente
fuente TEXT NOT NULL DEFAULT 'gesdai_dbf'
-- Valores futuros: 'excel_cuotas', 'csv_manual', etc.
```

Esto permite que el historial muestre claramente de dónde viene cada factura exportada.

### 3.5 Import/Export de datos

Todas las tablas gestionables por el usuario tienen capacidad de importación y exportación:

| Tabla | Export CSV | Export Excel | Import CSV | Import Excel |
|---|---|---|---|---|
| `mappings_clientes` | ✅ v1.0 | ✅ v1.0 | ✅ v1.0 | ✅ v1.0 |
| `mappings_articulos` | ✅ v1.0 | ✅ v1.0 | ✅ v1.0 | ✅ v1.0 |
| `keywords_articulos` | ✅ v1.0 | — | ✅ v1.0 | — |
| Historial de exportaciones | ✅ v1.0 | ✅ v1.0 | — | — |
| Preview de exportación | — | ✅ v1.0 | — | — |

---

## 4. Stack tecnológico

| Capa | Tecnología | Justificación |
|---|---|---|
| Backend | Python 3.11 + Flask 3.x | Ligero, conocido, compatible con PyInstaller; escala a servidor sin cambios |
| Base de datos intermediaria | SQLite 3 | Sin servidor, portable; migrable a PostgreSQL si se necesita servidor multi-usuario |
| Lectura DBF | `dbf` (PyPI) | Probado con los DBF de GESDAI, soporta `cp1252` |
| Excel import/export | `openpyxl` (PyPI) | Lectura y escritura de .xlsx sin dependencias externas |
| Frontend | HTML + Vanilla JS + CSS | Sin dependencias de build; funciona embebido en el .exe |
| Tests | `pytest` + `pytest-cov` | Estándar del ecosistema Python |
| Empaquetado | PyInstaller | .exe autocontenido para Windows |
| Actualizaciones | GitHub Releases API | Comprobación en arranque, descarga en background |
| Control de versiones | Git + GitHub (privado) | Privado por seguridad del código fuente |

---

## 5. Estructura del repositorio

```
gesdai-exporter/
│
├── app/
│   ├── __init__.py                 # Factory de Flask (create_app)
│   ├── config.py                   # Configuración por entorno (dev/prod)
│   ├── db.py                       # Inicialización, conexión y migraciones SQLite
│   │
│   ├── sources/                    # Fuentes de datos — interfaz abstracta + implementaciones
│   │   ├── __init__.py
│   │   ├── base.py                 # Interfaz abstracta DataSource + modelos comunes (Factura, Cliente, Articulo, Filtros)
│   │   └── dbf_source.py           # Implementación GESDAI (DBF/FoxPro), read-only
│   │
│   ├── mapping/                    # Lógica del intermediario
│   │   ├── __init__.py
│   │   ├── resolver.py             # Pipeline: mapping → keyword → default
│   │   └── keywords.py             # Motor de keyword matching
│   │
│   ├── exporter/                   # Generación del DAT
│   │   ├── __init__.py
│   │   ├── builder.py              # Construye registros Cabecera IVA + Detalle IVA
│   │   └── suenlace.py             # Formatea registros a 254 chars y escribe el DAT
│   │
│   ├── io/                         # Import/Export de datos del usuario
│   │   ├── __init__.py
│   │   ├── csv_handler.py          # Lectura y escritura CSV (mappings, historial)
│   │   └── excel_handler.py        # Lectura y escritura Excel (mappings, previews)
│   │
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── config_routes.py        # /config
│   │   ├── mappings.py             # /mappings/clientes, /mappings/articulos
│   │   ├── keywords.py             # /keywords
│   │   ├── export.py               # /export (filtros avanzados, preview, generar DAT)
│   │   └── history.py              # /historial
│   │
│   ├── static/
│   │   ├── app.css
│   │   └── app.js                  # Constructor de filtros AND/OR, semáforo, tabla de preview
│   │
│   └── templates/
│       ├── base.html
│       ├── config.html
│       ├── mappings_clientes.html
│       ├── mappings_articulos.html
│       ├── keywords.html
│       ├── export.html             # Incluye el constructor de filtros
│       └── historial.html
│
├── tests/
│   ├── conftest.py
│   ├── data/
│   │   └── DATA_DEV/               # DBFs sintéticos — nunca en el repo
│   ├── unit/
│   │   ├── test_dbf_source.py      # (antes test_reader.py)
│   │   ├── test_filtros.py         # Composición de filtros AND/OR
│   │   ├── test_resolver.py
│   │   ├── test_keywords.py
│   │   ├── test_builder.py
│   │   ├── test_suenlace.py
│   │   └── test_io.py              # CSV y Excel import/export
│   ├── integration/
│   │   ├── test_pipeline.py        # Flujo completo DBF → DAT con DATA_DEV
│   │   └── test_routes.py
│   └── validation/
│       └── test_dat_format.py      # 254 chars, encoding, estructura
│
├── scripts/
│   ├── generate_dev_data.py
│   └── check_dbf_structure.py
│
├── updater/
│   └── updater.py
│
├── main.py
├── gesdai_exporter.spec
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 6. Modelo de datos

### 6.1 Modelos de dominio (en `sources/base.py`)

```python
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum

@dataclass
class Cliente:
    codigo: str
    nombre: str
    nif: str | None
    razon_social: str | None

@dataclass
class LineaFactura:
    codigo_factura: str
    linea: int
    articulo: str        # clave o texto libre
    cantidad: Decimal
    precio: Decimal
    iva: Decimal
    total_linea: Decimal

@dataclass
class Factura:
    codigo: str
    serie: str
    numero: str
    cliente_codigo: str
    fecha: date
    total_base: Decimal
    total_con_iva: Decimal
    ptsbase1: Decimal; iva1: Decimal; recequi1: Decimal
    ptsbase2: Decimal; iva2: Decimal; recequi2: Decimal
    ptsbase3: Decimal; iva3: Decimal; recequi3: Decimal
    retirpf: Decimal
    contabil: bool       # informativo — nunca se escribe
    lineas: list[LineaFactura] = field(default_factory=list)
    fuente: str = 'gesdai_dbf'   # identificador de la fuente

class OperadorFiltro(Enum):
    AND = 'AND'
    OR  = 'OR'

@dataclass
class Condicion:
    campo: str       # 'fecha', 'cliente', 'serie', 'resolucion', 'importe'
    operador: str    # 'entre', 'igual', 'contiene', 'mayor_que', etc.
    valor: object

@dataclass
class Filtros:
    operador: OperadorFiltro = OperadorFiltro.AND
    condiciones: list['Condicion | Filtros'] = field(default_factory=list)
```

### 6.2 SQLite — Tablas del intermediario

```sql
CREATE TABLE config (
    clave       TEXT PRIMARY KEY,
    valor       TEXT NOT NULL,
    descripcion TEXT
);
-- Claves:
-- 'dbf_path'          → ruta al directorio de DBFs
-- 'exports_path'      → directorio de salida para los DAT
-- 'cuenta_ventas_def' → cuenta 700 por defecto (ej: 700001)
-- 'ejercicio'         → año contable activo
-- 'cod_empresa'       → código de empresa en a3ASESOR
-- 'importe_formato'   → 'A' (implícito ×100) o 'B' (decimal explícito)
-- 'schema_version'    → versión del esquema SQLite
-- 'app_version'       → versión de la aplicación

CREATE TABLE mappings_clientes (
    codigo_gesdai   TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    nif             TEXT,
    subcuenta_a3    TEXT,               -- 430XXX (NULL = pendiente)
    revisado        INTEGER DEFAULT 0,
    auto_matched    INTEGER DEFAULT 0,
    notas           TEXT,
    fecha_creacion  TEXT NOT NULL,
    fecha_revision  TEXT
);

CREATE TABLE mappings_articulos (
    clave_gesdai    TEXT PRIMARY KEY,
    descripcion     TEXT,
    cuenta_a3       TEXT,               -- 700XXX o 755XXX (NULL = pendiente)
    es_texto_libre  INTEGER DEFAULT 0,
    revisado        INTEGER DEFAULT 0,
    notas           TEXT,
    fecha_creacion  TEXT NOT NULL,
    fecha_revision  TEXT
);

CREATE TABLE keywords_articulos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword     TEXT NOT NULL UNIQUE,
    cuenta_a3   TEXT NOT NULL,
    prioridad   INTEGER DEFAULT 10,
    activo      INTEGER DEFAULT 1
);

CREATE TABLE exportaciones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha_export    TEXT NOT NULL,
    fecha_desde     TEXT NOT NULL,
    fecha_hasta     TEXT NOT NULL,
    filtros_json    TEXT,               -- filtros aplicados serializados
    num_facturas    INTEGER NOT NULL,
    dat_fichero     TEXT NOT NULL,
    dat_hash        TEXT NOT NULL,
    app_version     TEXT NOT NULL,
    validado        INTEGER DEFAULT 0,
    notas           TEXT
);

CREATE TABLE exportaciones_detalle (
    exportacion_id  INTEGER NOT NULL REFERENCES exportaciones(id),
    codigo_factura  TEXT NOT NULL,
    fuente          TEXT NOT NULL DEFAULT 'gesdai_dbf',  -- origen del dato
    cliente_gesdai  TEXT NOT NULL,
    subcuenta_a3    TEXT NOT NULL,
    total_coniva    REAL NOT NULL,
    resolucion_tipo TEXT NOT NULL,  -- 'mapping' | 'keyword' | 'default'
    PRIMARY KEY (exportacion_id, codigo_factura)
);
```

### 6.3 Validación de subcuentas

```python
import re

RE_SUBCUENTA_CLIENTE = re.compile(r'^430\d{3}$')
RE_SUBCUENTA_INGRESO = re.compile(r'^(700|705|755)\d{3}$')
RE_SUBCUENTA_GENERIC = re.compile(r'^\d{6}$')
```

### 6.4 Lógica de resolución de artículos

```
lfactura.ARTICULO
         │
         ▼
1. ¿Existe en mappings_articulos con revisado=1?
   └─ Sí → usa cuenta_a3                              [tipo: 'mapping']
         │ No
         ▼
2. Keyword matching (case-insensitive, prioridad DESC)
   └─ Match → guarda en mappings_articulos pendiente  [tipo: 'keyword']
         │ Sin match
         ▼
3. Cuenta por defecto (config.cuenta_ventas_def)
   └─ Marca como "requiere revisión"                  [tipo: 'default']
```

### 6.5 Campo CONTABIL de cfactura

`cfactura.CONTABIL` se lee como señal informativa (⚠️ en la UI) pero **nunca se escribe**. La decisión la toma siempre el usuario.

---

## 7. Especificación SUENLACE.DAT

> Fuente: `SUENLACE.XLS` de la instalación de a3ASESOR en COLVET.

### 7.1 Estructura general

- Fichero de texto plano, registros de **longitud fija: 254 caracteres**
- Fin de línea: **CRLF** (`\r\n`)
- Encoding: **`cp1252`** (Windows-1252) — pendiente confirmar con test
- Tipo de registro determinado por `tipreg` en posición 15

### 7.2 Tipos de registro usados

| Tipo | `tipreg` | Cuándo |
|---|---|---|
| Cabecera IVA | `1` | Una por factura |
| Detalle IVA | `9` | Una por cada `PTSBASE` > 0 |

### 7.3 Línea Cabecera IVA (`tipreg=1`)

| Pos | Long | Tipo | Campo | Valor |
|---|---|---|---|---|
| 1 | 1 | Num | `tipform` | `3` |
| 2 | 5 | Num | `codemp` | Código empresa, justificado derecha con ceros |
| 7 | 8 | Num | `fechafac` | `cfactura.FECHA` → `AAAAMMDD` |
| 15 | 1 | Num | `tipreg` | `1` (factura) · `2` (abono) |
| 16 | 12 | Alfa | `cuenta` | Subcuenta `430XXX`, paddeo con espacios a la derecha |
| 28 | 30 | Alfa | `descuenta` | Nombre del cliente, truncado a 30 |
| 58 | 1 | Num | `tipfac` | `1` (Ventas) |
| 59 | 10 | Alfa | `numfac` | `SERIE` + `NUMERO` de la factura |
| 69 | 1 | Alfa | `orden` | `I` (constante) |
| 70 | 30 | Alfa | `desfac` | Descripción del apunte, truncado a 30 |
| 100 | 14 | Num | `importe` | `cfactura.TOTCONIVA` — ver formato 7.5 |
| 114 | 139 | Alfa | `reserva` | Espacios |
| 253 | 1 | Alfa | `moneda` | `E` (euros) |
| 254 | 1 | Alfa | `ind-gen` | Espacio |

### 7.4 Línea Detalle IVA (`tipreg=9`)

Una por cada `PTSBASE` > 0. El `orden` del último detalle es `U`; los anteriores `M`.

| Pos | Long | Tipo | Campo | Valor |
|---|---|---|---|---|
| 1 | 1 | Num | `tipform` | `3` |
| 2 | 5 | Num | `cod-emp` | Código empresa |
| 7 | 8 | Num | `fechafac` | `cfactura.FECHA` → `AAAAMMDD` |
| 15 | 1 | Num | `tip-reg` | `9` (constante) |
| 16 | 12 | Alfa | `cuenta` | Subcuenta `700XXX`/`755XXX`, paddeo espacios |
| 28 | 30 | Alfa | `descuenta` | Descripción cuenta ventas, truncado a 30 |
| 58 | 1 | Alfa | `tipimp` | `C` (cargo/venta) |
| 59 | 10 | Alfa | `numfac` | Mismo número que la cabecera |
| 69 | 1 | Alfa | `orden` | `M` (intermedio) o `U` (último) |
| 70 | 30 | Alfa | `descrip` | Descripción, truncado a 30 |
| 100 | 2 | Num | `subtipo` | `1` (estándar — confirmar si a3 lo requiere distinto) |
| 102 | 14 | Num | `base` | `cfactura.PTSBASEn` |
| 116 | 5 | Num | `por-iva` | `cfactura.IVAn` |
| 121 | 14 | Num | `cuo-iva` | `base × por-iva / 100` |
| 135 | 5 | Num | `por-rec` | `cfactura.RECEQUIn` |
| 140 | 14 | Num | `cuo-rec` | `base × por-rec / 100` |
| 154 | 5 | Num | `por-ret` | `cfactura.RETIRPF` |
| 159 | 14 | Num | `cuo-ret` | `base × por-ret / 100` |
| 173 | 2 | Num | `impreso` | `0` |
| 175 | 1 | Alfa | `op-iva` | `S` |
| 176 | 77 | Alfa | `reserva` | Espacios |
| 253 | 1 | Alfa | `moneda` | `E` |
| 254 | 1 | Alfa | `ind-gen` | Espacio |

### 7.5 Formato de campos numéricos — a confirmar en Fase 5

| Opción | Formato importe 12,50€ | Formato IVA 21% |
|---|---|---|
| A — escala implícita (más probable) | `00000000001250` | `02100` |
| B — decimal explícito | `000000000012.50` | `21.00 ` |

Controlado por `config.importe_formato` (A/B). Se confirma en Fase 5 paso 7 exportando una factura de importe conocido e inspeccionando el DAT.

### 7.6 Mapeo GESDAI → SUENLACE

| Campo GESDAI | Campo SUENLACE | Registro |
|---|---|---|
| `cfactura.FECHA` | `fechafac` | Cabecera + Detalle |
| `cfactura.SERIE + NUMERO` | `numfac` | Cabecera + Detalle |
| `cfactura.TOTCONIVA` | `importe` | Cabecera |
| Mapping `cliente → 430XXX` | `cuenta` | Cabecera |
| `clientes.NOMBRE` | `descuenta` | Cabecera |
| `cfactura.PTSBASE1/2/3` | `base` | Detalle (uno por base > 0) |
| `cfactura.IVA1/2/3` | `por-iva` | Detalle |
| `cfactura.RECEQUI1/2/3` | `por-rec` | Detalle |
| `cfactura.RETIRPF` | `por-ret` | Detalle |
| Mapping `articulo → 700XXX/755XXX` | `cuenta` | Detalle |

---

## 8. Fases de desarrollo

---

### FASE 0 — Preparación del entorno
**Duración estimada:** 1 día

- [ ] Repositorio privado en GitHub
- [ ] `.gitignore` exhaustivo
- [ ] Entorno virtual + dependencias fijadas en `requirements.txt` y `requirements-dev.txt`
- [ ] Estructura de carpetas completa con `__init__.py` vacíos
- [ ] `DATA_DEV/` en `tests/data/` local — nunca al repo
- [ ] `pytest` configurado (`pyproject.toml`)
- [ ] Primer commit: esqueleto

**Criterio:** `pytest` arranca (0 tests, 0 fallos). `flask run` devuelve 200.

---

### FASE 1 — Interfaz abstracta de fuentes + implementación DBF
**Duración estimada:** 2–3 días  
**Objetivo:** La lógica de negocio nunca depende de GESDAI directamente.

- [ ] `sources/base.py`: dataclasses `Factura`, `LineaFactura`, `Cliente`, `Articulo`, `Filtros`, `Condicion`; clase abstracta `DataSource`
- [ ] `sources/dbf_source.py`: implementa `DataSource` para GESDAI
  - Apertura en `READ_ONLY`, `codepage='cp1252'`, cierre en `finally`
  - `get_facturas(filtros)` — aplica el árbol de filtros sobre `cfactura`
  - `get_cliente(codigo)`, `get_clientes()`, `get_articulos()`
  - Validación de campos al abrir: excepción descriptiva si falta alguno
  - Manejo de errores: DBF no encontrado, DBF bloqueado, campo corrupto

**Tests:**
```python
# test_dbf_source.py
test_implementa_interfaz_datasource()
test_apertura_es_read_only()
test_filtro_fecha_entre()
test_filtro_fecha_y_cliente_and()
test_filtro_cliente_or()
test_filtro_anidado_and_or()
test_rango_sin_resultados_devuelve_lista_vacia()
test_campos_texto_devueltos_con_strip()
test_cliente_no_encontrado_lanza_excepcion()
test_dbf_no_existe_lanza_excepcion_clara()
test_campo_esperado_ausente_lanza_excepcion()
test_contabil_se_lee_como_booleano()
test_ptsbase_cero_devuelto_como_cero()

# test_filtros.py
test_filtro_and_simple()
test_filtro_or_simple()
test_filtro_anidado()
test_filtro_vacio_devuelve_todo()
```

**Criterio:** Todos pasan. Cobertura `sources/` ≥ 90%.

---

### FASE 2 — Intermediario SQLite, mappings e IO
**Duración estimada:** 3 días  
**Objetivo:** Base de datos local, CRUD completo, import/export CSV y Excel.

- [ ] `db.py`: init, versión de esquema, migraciones automáticas
- [ ] Init idempotente: puebla mappings desde la fuente sin sobreescribir revisados
- [ ] CRUD mappings (clientes y artículos): get, set, marcar revisado
- [ ] `mapping/keywords.py`: matching case-insensitive con prioridad
- [ ] `io/csv_handler.py`: import y export CSV para mappings e historial
- [ ] `io/excel_handler.py`: import y export Excel (.xlsx) para mappings y previews

**Tests:**
```python
# test_dbf_source.py / test_io.py
test_init_idempotente()
test_set_subcuenta_6_digitos_validos()
test_set_subcuenta_7_digitos_error()
test_set_subcuenta_letras_error()
test_marcar_revisado()
test_importar_csv_carga_masiva()
test_importar_csv_no_sobreescribe_revisados()
test_importar_excel_carga_masiva()
test_exportar_csv_round_trip()
test_exportar_excel_round_trip()
test_keyword_match_case_insensitive()
test_keyword_prioridad()
test_keyword_sin_match_devuelve_none()
```

**Criterio:** Todos pasan. Init idempotente. Cobertura `mapping/` e `io/` ≥ 90%.

---

### FASE 3 — Motor de resolución y generador DAT
**Duración estimada:** 3–4 días  
**Prerequisito:** Código de empresa confirmado (sección 2.2).

- [ ] `mapping/resolver.py`: pipeline mapping → keyword → default, registra tipo
- [ ] `exporter/builder.py`:
  - Cabecera IVA + Detalle(s) IVA por factura (uno por `PTSBASE` > 0)
  - `orden` correcto: `I` en cabecera, `M`/`U` en detalles
  - Validación: `sum(bases) + sum(cuotas_iva) ≈ TOTCONIVA` (tolerancia 0,02€)
  - Error si cliente sin `subcuenta_a3`; error si factura ya exportada
- [ ] `exporter/suenlace.py`:
  - `_format_record(campos, spec)` → string de exactamente 254 chars
  - `_format_num(valor, longitud, formato)` → según `config.importe_formato`
  - `preview(facturas)` → lista en memoria, sin escribir
  - `exportar(facturas, ruta)` → DAT en `cp1252` + CRLF, SHA-256

**Tests:**
```python
test_factura_un_iva_genera_cabecera_y_un_detalle()
test_factura_dos_iva_genera_cabecera_y_dos_detalles()
test_ultimo_detalle_orden_U()
test_detalles_intermedios_orden_M()
test_cuadre_base_mas_iva_tolerancia_002()
test_ptsbase_cero_no_genera_detalle()
test_cliente_sin_subcuenta_error()
test_factura_ya_exportada_error()
test_registro_exactamente_254_chars()
test_cuenta_paddea_12_chars()
test_encoding_cp1252_caracteres_especiales()
test_preview_no_escribe_fichero()
test_exportar_crea_fichero_crlf()
test_hash_sha256_reproducible()
test_formato_importe_A()
test_formato_importe_B()
test_resolucion_mapping_sobre_keyword()
test_resolucion_keyword_cuando_no_hay_mapping()
test_resolucion_default_sin_keyword()
test_texto_libre_se_guarda_pendiente()
```

**Criterio:** Pipeline completo con `DATA_DEV` genera DAT sin errores. Todos los registros son 254 chars. Cobertura `exporter/` y `mapping/` ≥ 90%.

---

### FASE 4 — Interfaz web
**Duración estimada:** 5–6 días  
**Objetivo:** UI completa con filtrado avanzado, semáforo y gestión de mappings.

#### 4.1 Panel de configuración (`/config`)
- Ruta a los DBFs con "Verificar conexión"
- Directorio de salida, código de empresa, cuenta por defecto, ejercicio
- Toggle `importe_formato` A/B

#### 4.2 Panel de mappings — Clientes (`/mappings/clientes`)
- Tabla paginada: código / nombre / NIF / subcuenta / estado
- Filtro: todos / pendientes / revisados
- Edición inline con validación `430XXX`
- Botón "Marcar revisado"
- Import/export CSV y Excel
- Indicador de progreso

#### 4.3 Panel de mappings — Artículos (`/mappings/articulos`)
- Igual que clientes + columna "origen"
- Subcuenta `700XXX` o `755XXX`

#### 4.4 Panel de keywords (`/keywords`)
- Lista, prioridad, añadir/editar/eliminar
- Campo "Probar": texto → muestra qué keyword matchea

#### 4.5 Panel de exportación (`/export`)

**Constructor de filtros avanzado:**
- Condiciones sobre: fecha, cliente, serie, estado de resolución, importe
- Grupos de condiciones con operador AND/OR por grupo
- Botón "+ Condición" y "+ Grupo" para componer filtros
- Botón "Limpiar filtros" y presets guardables (ej: "Mes actual", "Pendientes")

**Vista previa con semáforo:**
- 🟢 Verde — cliente revisado + todos los artículos por mapping
- 🟡 Amarillo — algún artículo por keyword o default (exportable)
- 🔴 Rojo — cliente sin `subcuenta_a3` (bloquea)
- ⚪ Gris — ya exportada (excluida automáticamente)
- ⚠️ Aviso — `CONTABIL=True` en GESDAI (informativo)

Resumen: N facturas, N registros DAT, importe total, N pendientes  
"Generar DAT" deshabilitado con cualquier rojo  
Descarga automática al generar  
**Export de la preview a Excel** (para revisión externa)

#### 4.6 Historial (`/historial`)
- Lista de exportaciones: fecha, rango, filtros, N facturas, hash
- Descargar DAT anterior
- Marcar como validado en a3ASESOR
- Export del historial a CSV y Excel

**Tests:**
```python
test_get_config_200()
test_post_config_ruta_invalida_400()
test_get_mappings_clientes_200()
test_post_subcuenta_correcto_200()
test_post_subcuenta_7_digitos_400()
test_post_subcuenta_letras_400()
test_get_preview_sin_filtros_200()
test_get_preview_con_filtros_and_200()
test_get_preview_con_filtros_or_200()
test_post_dat_con_rojo_400()
test_post_dat_correcto_crea_fichero()
test_get_historial_200()
test_import_csv_correcto()
test_import_csv_invalido_400()
test_import_excel_correcto()
test_export_preview_excel()
```

**Criterio:** UI funciona en Chrome y Edge. Filtros AND/OR producen resultados coherentes. "Generar DAT" solo activo sin rojos.

---

### FASE 5 — Validación contable con datos reales
**Duración estimada:** 1–2 sesiones  
**Se realiza en el PC de COLVET.**

1. Instalar app en modo dev en el PC de COLVET
2. Configurar ruta `C:\GESDAI\DATA` y código de empresa; verificar conexión
3. Inicializar mappings desde los DBF reales
4. Cargar CSV/Excel de carga inicial de clientes
5. Revisar los 59 artículos del catálogo y configurar keywords
6. **Confirmar `importe_formato`**: exportar 1 factura de importe conocido, inspeccionar DAT
7. Exportar 2–3 facturas conocidas de un mes ya cerrado
8. Importar DAT en a3ASESOR en **ejercicio de prueba** (no el real)
9. Verificar asientos con Anguix
10. Si errores → corregir y repetir desde 7
11. Limpiar los asientos de prueba en a3ASESOR
12. Si todo correcto: exportar un mes completo como segunda validación

**Criterio:** DAT importado sin errores. Asientos correctos. `importe_formato` documentado.

---

### FASE 6 — Empaquetado y auto-updater
**Duración estimada:** 2–3 días

- [ ] `gesdai_exporter.spec`: templates, static, `dbf`, `openpyxl`, icono, `--onefile`
- [ ] `updater/updater.py`: GitHub API → descarga → SHA-256 → banner o descarte
- [ ] `main.py`: updater → Flask → navegador + systray
- [ ] SQLite en `%APPDATA%\GesdaiExporter\`
- [ ] GitHub Actions: build en cada tag → publica `.exe` en release

```yaml
on:
  push:
    tags: ['v*']
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt pyinstaller
      - run: pyinstaller gesdai_exporter.spec
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/gesdai_exporter.exe
```

**Criterio:** .exe arranca sin Python. Updater funciona. SQLite intacto tras actualización.

---

### FASE 7 — Entrega y formación
**Duración estimada:** 1 día

Instalador v1.0: el propio `.exe`. Sin Inno Setup hasta v2.0.

- [ ] Manual de usuario PDF: configuración, flujo mensual, gestión de mappings y filtros
- [ ] Guía de procedimiento mensual (1 página)
- [ ] Sesión de formación (~1 hora)
- [ ] Canal de soporte definido

---

## 9. Plan de tests

### Pirámide

```
         ▲
        /E2E\         1–2 pruebas manuales en a3ASESOR (Fase 5)
       /──────\
      /Integr. \      ~15 tests: pipeline completo, endpoints
     /────────── \
    / Unitarios   \   ~55 tests: lógica aislada, sin ficheros ni red
   /───────────────\
```

### Cobertura mínima

| Módulo | Mínimo |
|---|---|
| `sources/dbf_source.py` | 90% |
| `sources/base.py` | 85% |
| `mapping/resolver.py` | 95% |
| `mapping/keywords.py` | 95% |
| `exporter/builder.py` | 95% |
| `exporter/suenlace.py` | 90% |
| `io/` | 85% |
| `routes/` | 80% |

### CI

```yaml
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements-dev.txt
      - run: pytest tests/unit/ --cov=app --cov-fail-under=85
```

`DATA_DEV/` no está en el repo. Los tests de integración solo se ejecutan en local.

---

## 10. Distribución y despliegue

### Versionado semántico

```
MAJOR . MINOR . PATCH
  │       │       └─ Corrección, sin cambios de esquema
  │       └───────── Nueva funcionalidad, esquema compatible
  └───────────────── Cambio de esquema SQLite (migración automática)
```

### Proceso de release

```
1. Tests pasan en local y CI
2. Bump versión en config.py y .spec
3. git tag vX.Y.Z && git push --tags
4. GitHub Actions compila y publica .exe
5. Updater lo detecta en el siguiente arranque
```

---

## 11. Sistema de actualizaciones

```
Arranque
    ├─ Sin conexión ──────────────────────► continuar (silencioso)
    ├─ Versión == última ─────────────────► continuar normal
    └─ Versión nueva
           ├─ SHA-256 falla → descartar, avisar
           └─ SHA-256 OK → banner "Actualización disponible"
                           │ confirma
                           └─ reemplazar .exe → reiniciar
```

SQLite en `%APPDATA%\GesdaiExporter\` — nunca se toca en una actualización.

---

## 12. Seguridad y protección de datos

- Herramienta interna de COLVET — no aplica encargo externo de tratamiento
- `dbf_source.py` abre siempre en `READ_ONLY` — imposible escritura accidental
- App 100% local en v1.0; ningún dato sale del equipo
- SQLite contiene solo mappings (códigos y subcuentas), no datos personales completos
- `.gitignore` excluye `*.dbf`, `*.db`, `DATA_DEV/`, `exports/`, `.env`
- Repositorio GitHub privado

---

## 13. Criterios de aceptación por fase

| Fase | Criterio principal | Criterio de calidad |
|---|---|---|
| 0 | `pytest` y `flask run` funcionan | Estructura completa |
| 1 | Interfaz abstracta implementada; filtros AND/OR funcionan | Cobertura `sources/` ≥ 90% |
| 2 | Mappings persisten; CSV/Excel import/export funcionan | Cobertura `mapping/` e `io/` ≥ 90% |
| 3 | DAT con registros de 254 chars exactos | Cobertura `exporter/` ≥ 90% |
| 4 | UI completa; filtros avanzados; sin rojos = DAT activo | Sin errores Chrome/Edge |
| 5 | DAT importado en a3ASESOR; `importe_formato` confirmado | Anguix valida asientos |
| 6 | .exe sin Python; updater funciona | SQLite intacto tras update |
| 7 | Usuario opera sin ayuda; manual entregado | Canal de soporte definido |

---

## 14. Riesgos y mitigaciones

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| Formato numérico de importes incorrecto (A vs B) | Media | Medio | `config.importe_formato` configurable; se confirma en Fase 5 |
| GESDAI bloquea el DBF durante la lectura | Baja | Medio | Excepción capturada con mensaje claro; exportar fuera de horario de uso |
| Actualización de GESDAI cambia estructura de DBFs | Baja | Alto | Validación de campos al arrancar; alerta si falta alguno |
| Pérdida del SQLite (mappings manuales) | Baja | Alto | Export a CSV/Excel desde la UI; recordatorio periódico |
| Artículo nuevo no cubierto por keywords | Alta | Bajo | Marcado en amarillo; se añade antes de la siguiente exportación |
| Límite 999 slots `430XXX` | Baja | Medio | Con 552 clientes hay margen; ampliar rango con Anguix si se supera |
| `subtipo` incorrecto en Detalle IVA | Baja | Bajo | Valor `1` estándar; fácil corregir en config |

---

## 15. Hoja de ruta post-producción

### v1.1 — Mejoras de usabilidad
- Sugerencia automática de `430XXX` por NIF al importar
- Dashboard de inicio: exportaciones recientes, mappings pendientes, mes a exportar
- Presets de filtros guardables por el usuario
- Filtro por serie de factura en el panel de exportación

### v1.2 — Automatización del matching
- Aprendizaje de keywords a partir del historial
- Detección de artículos similares ya mapeados

### v2.0 — Nuevas fuentes y escalado
- `sources/excel_source.py`: facturas desde Excel (mismos clientes, distinta fuente)
- Instalador Inno Setup para más equipos
- Opción de despliegue en servidor local de red (sin cambios de arquitectura gracias a `sources/`)
- Autenticación básica para acceso multi-usuario

### v3.0 — Automatización total
- Importación programática en a3ASESOR si expone API u ODBC
- Ejecución desatendida programada (sin intervención manual)

---

## 16. Apéndice — Decisiones de diseño

| ID | Decisión | Alternativa | Razón |
|---|---|---|---|
| D01 | GESDAI siempre read-only | Marcar `cfactura.CONTABIL` | Riesgo de corrupción inaceptable |
| D02 | Tracking en SQLite propio | Confiar en `cfactura.CONTABIL` | Independencia de GESDAI; trazabilidad con SHA-256 |
| D03 | Resolución artículos en 3 pasos | Solo keyword matching | Mappings precisos coexisten con automatización parcial |
| D04 | Flask local + navegador | tkinter | UI más rica; navegador ya instalado; escala a servidor sin cambios |
| D05 | SQLite en `%APPDATA%` | Junto al .exe | Sobrevive a actualizaciones; sin permisos de admin |
| D06 | Auto-updater vía GitHub Releases | Manual | Siempre en la última versión sin intervención |
| D07 | CSV + Excel import en v1.0 | Solo edición manual | 552 clientes son inviables de mapear uno a uno |
| D08 | Sin Inno Setup en v1.0 | Instalador profesional | Herramienta monousuario; complejidad no justificada aún |
| D09 | Subcuentas de 6 dígitos (`430XXX`) | 8 dígitos | Restricción del plan de cuentas de COLVET en a3ASESOR |
| D10 | Cabecera IVA + Detalle IVA | Asientos de diario | Formato nativo de facturas; a3ASESOR gestiona el 477 automáticamente |
| D11 | `importe_formato` configurable (A/B) | Hardcodeado | El spec no especifica el formato; se confirma en Fase 5 sin tocar código |
| D12 | `sources/` con interfaz abstracta | `dbf/` acoplado | Nuevas fuentes (Excel, CSV) sin tocar lógica de negocio |
| D13 | Filtros AND/OR como árbol de condiciones | Solo filtro de fecha | Requisito de filtrado avanzado; estructura extensible sin reescribir |
| D14 | Campo `fuente` en `exportaciones_detalle` | Sin campo fuente | Soporte futuro de múltiples fuentes por cliente en el historial |

---

*Documento vivo — actualizar ante cualquier cambio de alcance, decisión técnica o hallazgo durante el desarrollo.*
