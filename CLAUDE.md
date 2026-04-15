# gesdai-exporter

Herramienta local para COLVET Guadalajara que lee facturas de GESDAI (DBF/FoxPro), las convierte al formato `SUENLACE.DAT` de a3ASESOR y gestiona el mapeo cliente/artículo → subcuenta contable mediante una UI web embebida.

Plan de desarrollo completo en [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md) — referencia obligada antes de cambios de arquitectura, alcance o formato de datos.

## Stack

- Runtime: Python 3.11
- Framework: Flask 3.x (servidor local embebido, navegador como UI)
- Base de datos intermediaria: SQLite 3 (en `%APPDATA%\GesdaiExporter\`)
- Lectura DBF: `dbf` (PyPI) con `codepage='cp1252'`, siempre `READ_ONLY`
- Import/export tabular: `openpyxl` (xlsx) + módulo csv estándar
- Frontend: HTML + Vanilla JS + CSS (sin build, embebido en el .exe)
- Tests: `pytest` + `pytest-cov`
- Empaquetado: PyInstaller (`--onefile`, Windows)
- Auto-updater: GitHub Releases API + verificación SHA-256
- Control de versiones: Git + GitHub (repo privado)

## Comandos

- `flask --app app run --debug`: Servidor de desarrollo
- `python main.py`: Arranque como app de escritorio (updater + Flask + navegador + systray)
- `pytest tests/unit/`: Tests unitarios (rápidos, sin DBF reales)
- `pytest tests/integration/`: Tests de integración (requieren `tests/data/DATA_DEV/` local)
- `pytest tests/unit/test_builder.py::test_registro_exactamente_254_chars`: Ejecutar un test concreto — preferir esto sobre la suite completa durante desarrollo
- `pytest --cov=app --cov-fail-under=85`: Cobertura (umbral CI)
- `pyinstaller gesdai_exporter.spec`: Build del .exe autocontenido
- `python scripts/generate_dev_data.py`: Genera DBFs sintéticos en `tests/data/DATA_DEV/`
- `python scripts/check_dbf_structure.py`: Inspecciona estructura de un DBF (debug)

## Arquitectura

```
app/
  sources/         — fuentes de datos abstractas (base.py) + GESDAI DBF (dbf_source.py)
  mapping/         — resolver (mapping → keyword → default) + motor de keywords
  exporter/        — builder (cabecera + detalles IVA) + suenlace (formato 254 chars)
  io/              — import/export CSV y Excel
  routes/          — blueprints Flask: config, mappings, keywords, export, historial
  templates/       — Jinja2 + constructor de filtros AND/OR
  static/          — app.js (vanilla), app.css
  db.py            — init SQLite, versión de esquema, migraciones automáticas
  config.py        — configuración por entorno
tests/
  unit/  integration/  validation/  data/DATA_DEV/  (nunca en el repo)
scripts/           — utilidades de desarrollo (dev data, debug DBF)
updater/           — comprobación en arranque vía GitHub Releases
main.py            — entry point de escritorio
gesdai_exporter.spec  — build de PyInstaller
```

Ver Sección 5 de [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md) para el árbol completo.

## Flujo de trabajo

### Antes de implementar

- Identifica primero la fase activa del plan (Sección 8). Cada fase tiene criterios de aceptación concretos — no adelantar trabajo de fases posteriores sin discutirlo.
- Si el cambio toca más de 2 archivos o afecta a la capa `sources/`, `mapping/` o `exporter/`, entra en Plan Mode antes de escribir código.
- Si no conoces bien esta parte del codebase, usa subagentes para investigar.

### Durante la implementación

- **La lógica de negocio (`mapping/`, `exporter/`, `routes/`) nunca importa `dbf_source.py` directamente** — solo la interfaz abstracta `DataSource` de `sources/base.py`. Añadir fuentes nuevas (Excel, CSV) debe ser posible sin tocar nada fuera de `sources/`.
- Los DBF de GESDAI se abren **siempre** en `READ_ONLY` con `cp1252`, con cierre garantizado en `finally`. Cualquier escritura sobre GESDAI es un bug crítico.
- Toda I/O (DBF, SQLite, filesystem, HTTP del updater) maneja errores con excepciones descriptivas. Nunca silenciar fallos — si un dato no se puede resolver, se marca en la tabla de resolución (`tipo: default`) y se refleja en el semáforo.
- Logging estructurado (módulo `logging`) — nunca `print()` en código que se mergea.
- Cada endpoint Flask y cada función pública de `sources/`, `mapping/` y `exporter/` valida sus entradas (subcuentas con regex `^430\d{3}$` / `^(700|705|755)\d{3}$`, filtros bien formados, rutas existentes).
- Escribe tests en paralelo a la feature. Apunta a las coberturas de la Sección 9 del plan: `sources/` ≥ 90%, `mapping/` ≥ 95%, `exporter/` ≥ 90%, `io/` ≥ 85%, `routes/` ≥ 80%.

### Después de implementar

- Ejecuta `pytest tests/unit/` y el linter antes de cerrar la tarea.
- Si modificaste el esquema SQLite, bumpea `schema_version` en `config.py` y añade migración en `db.py`. Las migraciones son automáticas al arranque.
- Si modificaste el formato de `SUENLACE.DAT`, los tests de `validation/test_dat_format.py` deben pasar (254 chars exactos, CRLF, cp1252).

## Observabilidad

- Excepciones no controladas se loguean con contexto (fase, fichero, factura afectada) y se muestran en la UI con mensaje comprensible — nunca stack trace crudo al usuario.
- Toda exportación DAT generada queda registrada en la tabla `exportaciones` con: fecha, rango, filtros JSON, nº facturas, ruta, SHA-256 y versión de app. Trazabilidad total no es opcional.
- Logs en JSON estructurado con: timestamp, level, message, action (`dbf_read`, `dat_write`, `mapping_resolve`, etc.), y contexto relevante (código de factura, cliente, exportación_id).
- No hay Sentry en v1.0 (app 100% local) — los errores se escriben a fichero de log local rotado.

## Seguridad — REGLAS NO NEGOCIABLES

- **GESDAI es READ-ONLY siempre.** Ningún código puede escribir, renombrar o bloquear ficheros bajo `dbf_path`. Abrir en `READ_ONLY`, cerrar en `finally`. Esta regla es inviolable.
- **Nunca commitear** `*.dbf`, `*.db`, `DATA_DEV/`, `exports/`, `.env`, `SUENLACE.DAT` generados, ni ningún fichero con datos reales de COLVET. El `.gitignore` debe reflejarlo.
- **Nunca modificar `cfactura.CONTABIL`** ni ningún campo de GESDAI aunque parezca el camino fácil (Decisión D01 del plan). El tracking de qué se ha exportado vive en el SQLite propio, no en GESDAI.
- **Nunca ejecutar migraciones destructivas** (`DROP TABLE`, `DELETE` sin `WHERE`) sobre el SQLite del usuario sin confirmación explícita. Las migraciones de esquema solo añaden/transforman, nunca pierden mappings revisados.
- **Nunca exponer stack traces** al usuario final. Los errores se muestran como mensaje UI; el detalle va al log.
- Toda entrada de usuario (rutas, CSVs/Excels importados, filtros, subcuentas) es hostil hasta que se valida con regex o schema.
- Las dependencias nuevas requieren justificación explícita — la lista del Stack (`dbf`, `openpyxl`, `flask`, `pytest`, `pyinstaller`) es la línea base. No añadir paquetes para tareas triviales.
- Repositorio GitHub **privado** por política de seguridad del código fuente.

## Convenciones del proyecto

- **Nunca acoplar lógica de negocio a una fuente concreta.** Todo lo que esté fuera de `sources/` trabaja con los modelos de `sources/base.py` (`Factura`, `LineaFactura`, `Cliente`, `Articulo`, `Filtros`, `Condicion`).
- **Nada de `localhost` hardcodeado** en templates ni en JS — URLs relativas siempre. La app está diseñada para mover a servidor sin reescribir rutas.
- **Nada de rutas hardcodeadas** como `C:\GESDAI\` o `C:\exports\` — todo viene de la tabla `config` de SQLite (claves: `dbf_path`, `exports_path`, `cuenta_ventas_def`, `ejercicio`, `cod_empresa`, `importe_formato`).
- **Importes y decimales**: usar `Decimal`, nunca `float` en cálculos contables. El cuadre `sum(bases) + sum(cuotas_iva) ≈ TOTCONIVA` tiene tolerancia de 0,02€.
- **Subcuentas**: siempre 6 dígitos en el dominio, padeadas a 12 caracteres con espacios a la derecha al escribir en SUENLACE. Clientes `430XXX`, ventas `700XXX`, ingresos `755XXX`.
- **Filtros**: árbol `Filtros`/`Condicion` con operadores `AND`/`OR`. No exponer query builder genérico al usuario — solo los campos definidos en Sección 3.2 del plan (fecha, cliente, serie, estado resolución, importe).
- **Resolución de artículos**: orden estricto `mapping (revisado=1) → keyword (prioridad DESC) → default`. El tipo (`mapping` | `keyword` | `default`) se persiste en `exportaciones_detalle.resolucion_tipo`.
- **Tests de integración** con `DATA_DEV/` solo corren en local — no en CI (los DBFs sintéticos no están en el repo).

## Contexto de dominio

- **COLVET Guadalajara** usa GESDAI para facturación y a3ASESOR para contabilidad. Hoy introducen los asientos contables a mano mensualmente. Esta herramienta elimina ese trabajo manual.
- **~552 clientes activos** en GESDAI. Rango `430001–430999` suficiente. Carga inicial vía CSV/Excel — inviable mapear uno a uno manualmente.
- **Catálogo de ~59 artículos** — suficientemente pequeño para revisarse en Fase 5 y configurar keywords a mano.
- **Semáforo de exportación**: 🟢 verde (cliente revisado + artículos por mapping), 🟡 amarillo (algún artículo por keyword o default, exportable), 🔴 rojo (cliente sin subcuenta, bloquea), ⚪ gris (ya exportada, excluida). Cualquier rojo deshabilita "Generar DAT".
- **Formato SUENLACE.DAT**: texto plano, registros de **254 caracteres exactos**, línea `CRLF`, encoding `cp1252`. Tipo de registro en posición 15: `1` = Cabecera IVA (una por factura), `9` = Detalle IVA (uno por `PTSBASE` > 0). Orden: `I` en cabecera; `M`/`U` en detalles (último = `U`).
- **`importe_formato` A vs B**: A = escala implícita (12,50€ → `00000000001250`), B = decimal explícito (`000000000012.50`). Configurable, se confirma empíricamente en Fase 5 exportando una factura conocida.
- **`cfactura.CONTABIL`** se lee como aviso informativo (⚠️ en UI) pero nunca se escribe ni se usa como fuente de verdad — el tracking vive en `exportaciones` (SQLite propio).
- Especificación completa de campos SUENLACE en Sección 7 de [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md). Modelo de datos y SQLite en Sección 6.

## Restricciones de entorno

- **Windows-only** (COLVET usa Windows). Build `windows-latest` en CI. Empaquetado con PyInstaller `.exe` `--onefile`. No hay versión macOS/Linux en la hoja de ruta.
- **App 100% local en v1.0** — ningún dato sale del equipo. Sin telemetría, sin Sentry, sin API externa (salvo GitHub Releases para updater).
- **GESDAI puede bloquear los DBF** si hay usuarios usándolo simultáneamente. Capturar la excepción con mensaje claro ("GESDAI está en uso, intenta fuera del horario de trabajo").
- **SQLite vive en `%APPDATA%\GesdaiExporter\`** — sobrevive a actualizaciones del .exe. Nunca junto al ejecutable.
- **Sin Python en el PC objetivo** — el .exe debe arrancar solo. Verificar en Fase 6.
- **Subcuentas limitadas a 6 dígitos** en el plan de cuentas de COLVET (Decisión D09). No es renegociable sin hablar con Anguix (contable de COLVET).

## Compactación

Cuando se compacte la conversación, preservar siempre:

- Fase activa del plan y criterios de aceptación pendientes
- Lista completa de archivos modificados en la sesión
- Decisiones arquitectónicas tomadas y su justificación (especialmente cualquier desviación del plan)
- Estado de `importe_formato` si se confirmó en Fase 5
- Comandos de test relevantes para lo que se está tocando
- Errores encontrados con DBFs reales y cómo se resolvieron
