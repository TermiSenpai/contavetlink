# AGENTS.md

Guía para agentes de IA (Claude Code, Codex, Cursor, Aider, etc.) que trabajen en este repositorio. Este fichero sigue el estándar [agents.md](https://agents.md) y complementa a [CLAUDE.md](CLAUDE.md) (instrucciones específicas de Claude Code) y al [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md) (especificación funcional).

> **Orden de precedencia**: instrucciones del usuario en chat → CLAUDE.md / AGENTS.md → PLAN_DESARROLLO.md → defaults del agente.

---

## 1. Resumen del proyecto

**gesdai-exporter** es una herramienta local de escritorio (Flask + navegador embebido) para COLVET Guadalajara. Lee facturas desde GESDAI (DBF/FoxPro **read-only**), las convierte al formato `SUENLACE.DAT` de a3ASESOR y mantiene el mapeo cliente/artículo → subcuenta contable en SQLite.

- **Dominio**: contabilidad veterinaria (~552 clientes, ~59 artículos).
- **Plataforma objetivo**: Windows (despliegue como `.exe` autocontenido con PyInstaller).
- **Privacidad**: app 100% local. Ningún dato sale del equipo. Repo privado.

---

## 2. Stack

| Capa | Tecnología |
|------|-----------|
| Runtime | Python 3.11 |
| Web | Flask 3.x (servidor local) + Vanilla JS + Jinja2 |
| Persistencia local | SQLite 3 (en `%APPDATA%\GesdaiExporter\`) |
| Lectura DBF | `dbf` (PyPI) — siempre `READ_ONLY`, `codepage='cp1252'` |
| I/O tabular | `openpyxl` + módulo `csv` estándar |
| Tests | `pytest` + `pytest-cov` (umbral CI: 85%) |
| Empaquetado | PyInstaller (`--onefile`, Windows) |

No añadas dependencias sin justificación explícita. La lista anterior es la línea base.

---

## 3. Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
python scripts/generate_dev_data.py   # genera tests/data/DATA_DEV/
```

---

## 4. Comandos esenciales

```bash
# Desarrollo
flask --app app run --debug              # servidor web de desarrollo
python main.py                            # app de escritorio completa (updater + Flask + browser + systray)

# Tests
pytest tests/unit/                        # rápidos, sin DBF reales — usar siempre durante desarrollo
pytest tests/integration/                 # requieren DATA_DEV/ local (no corren en CI)
pytest tests/unit/test_builder.py::test_registro_exactamente_254_chars   # test individual
pytest --cov=app --cov-fail-under=85      # cobertura (gate de CI)

# Build
pyinstaller gesdai_exporter.spec          # genera .exe Windows

# Utilidades
python scripts/check_dbf_structure.py     # inspecciona estructura de un DBF
```

**Preferir tests individuales sobre la suite completa** durante iteración. Ejecuta la suite entera antes de cerrar la tarea.

---

## 5. Arquitectura

```
app/
  sources/      — fuentes de datos abstractas (base.py) + GESDAI DBF (dbf_source.py)
  mapping/      — resolver (mapping → keyword → default) + motor de keywords
  exporter/     — builder (cabecera + detalles IVA) + suenlace (formato 254 chars)
  io/           — import/export CSV y Excel
  routes/       — blueprints Flask (config, mappings, keywords, export, historial)
  templates/    — Jinja2 + constructor de filtros AND/OR
  static/       — app.js (vanilla), app.css
  db.py         — init SQLite, schema_version, migraciones automáticas
  config.py     — configuración por entorno
tests/          — unit/, integration/, validation/, data/DATA_DEV/ (gitignored)
scripts/        — utilidades de desarrollo
updater/        — auto-update vía GitHub Releases API + SHA-256
main.py         — entry point de escritorio
```

**Regla arquitectónica clave**: la lógica de negocio (`mapping/`, `exporter/`, `routes/`) **nunca** importa `dbf_source.py` directamente. Solo trabaja contra la interfaz abstracta `DataSource` y los modelos de `sources/base.py` (`Factura`, `LineaFactura`, `Cliente`, `Articulo`, `Filtros`, `Condicion`). Añadir una fuente nueva (Excel, CSV, API) no debe requerir cambios fuera de `sources/`.

---

## 6. Reglas de seguridad no negociables

1. **GESDAI es READ-ONLY siempre.** Abrir con `READ_ONLY`, cerrar en `finally`. Ningún código puede escribir, renombrar ni bloquear ficheros bajo `dbf_path`. Cualquier escritura es un bug crítico.
2. **Nunca modificar `cfactura.CONTABIL`** ni ningún campo de GESDAI, aunque parezca el camino fácil. El tracking de qué se ha exportado vive en la tabla `exportaciones` del SQLite propio, no en GESDAI.
3. **Nunca commitear** `*.dbf`, `*.db`, `DATA_DEV/`, `exports/`, `.env`, `SUENLACE.DAT` generados ni ningún fichero con datos reales de COLVET. Verifica `.gitignore`.
4. **Nunca exponer stack traces al usuario final.** Los errores se muestran como mensaje UI legible; el detalle va al log estructurado.
5. **Nunca ejecutar migraciones destructivas** (`DROP TABLE`, `DELETE` sin `WHERE`) sobre el SQLite del usuario. Las migraciones solo añaden o transforman, nunca pierden mappings revisados.
6. **Toda entrada de usuario es hostil** hasta validarla: rutas, CSV/Excel importados, filtros, subcuentas (regex `^430\d{3}$` para clientes, `^(700|705|755)\d{3}$` para cuentas de venta/ingreso).
7. **Repositorio privado**. No publicar fragmentos del código fuente externamente.

---

## 7. Convenciones de código

- **Decimales contables**: `decimal.Decimal`, nunca `float`. Tolerancia de cuadre `sum(bases) + sum(cuotas_iva) ≈ TOTCONIVA` = 0,02 €.
- **Subcuentas**: 6 dígitos en el dominio. Se padean a 12 caracteres (espacios a la derecha) al escribir en `SUENLACE.DAT`.
- **Logging**: módulo `logging` con JSON estructurado (`timestamp`, `level`, `message`, `action`, contexto). Nunca `print()` en código que se mergea.
- **Rutas y URLs**: nada hardcodeado. Las rutas (`dbf_path`, `exports_path`) viven en la tabla `config` de SQLite. En frontend, URLs relativas — nunca `localhost`.
- **Validación**: cada endpoint Flask y cada función pública de `sources/`, `mapping/`, `exporter/` valida sus entradas explícitamente.
- **Manejo de errores**: excepciones descriptivas, cierre garantizado de recursos en `finally`. Si un dato no resuelve, se marca `tipo: default` en la tabla de resolución y se refleja en el semáforo. Nunca silenciar fallos.
- **Resolución de artículos**: orden estricto `mapping (revisado=1) → keyword (prioridad DESC) → default`. El tipo se persiste en `exportaciones_detalle.resolucion_tipo`.
- **Filtros**: árbol `Filtros`/`Condicion` con operadores `AND`/`OR` sobre los campos definidos en la Sección 3.2 del plan. No exponer query builder genérico.

---

## 8. Formato SUENLACE.DAT (crítico)

- Texto plano, registros de **254 caracteres exactos**, terminador `CRLF`, encoding `cp1252`.
- Tipo de registro en posición 15: `1` = Cabecera IVA (una por factura), `9` = Detalle IVA (uno por `PTSBASE > 0`).
- Orden: `I` (insert) en cabecera; `M`/`U` en detalles, último siempre `U`.
- `importe_formato`:
  - `A` = escala implícita (12,50 € → `00000000001250`)
  - `B` = decimal explícito (`000000000012.50`)
  - Configurable, se confirma empíricamente exportando una factura conocida.

Si modificas el formato, los tests de `tests/validation/test_dat_format.py` **deben** pasar (254 chars exactos, CRLF, cp1252). Especificación completa: Sección 7 de [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md).

---

## 9. Testing

- **TDD recomendado** para `exporter/` y `mapping/` (lógica crítica con casos límite).
- Coberturas objetivo (Sección 9 del plan):
  - `sources/` ≥ 90%
  - `mapping/` ≥ 95%
  - `exporter/` ≥ 90%
  - `io/` ≥ 85%
  - `routes/` ≥ 80%
- Tests de integración con `DATA_DEV/` solo en local (DBFs sintéticos no commiteados).
- Antes de cerrar tarea: `pytest tests/unit/` debe pasar al 100%.
- Si tocas SQLite: añade test de migración en `tests/unit/test_db_migrations.py` y bumpea `schema_version` en `config.py`.

---

## 10. Flujo de trabajo del agente

### Antes de implementar
1. Identifica la **fase activa** del plan ([PLAN_DESARROLLO.md](PLAN_DESARROLLO.md) Sección 8). No adelantes trabajo de fases posteriores sin discutirlo.
2. Si el cambio toca más de 2 archivos o afecta a `sources/`, `mapping/` o `exporter/` → **plan explícito antes de tocar código**.
3. Lee primero el código existente que vas a modificar. No asumas.

### Durante
- Escribe tests en paralelo a la feature, no después.
- Mantén las funciones pequeñas y con tipos explícitos (type hints obligatorios en código nuevo).
- No añadas comentarios obvios. Solo el *porqué* no evidente (invariantes ocultos, workarounds, restricciones del dominio).
- No introduzcas abstracciones especulativas. Tres líneas similares es mejor que una abstracción prematura.

### Después
1. Ejecuta `pytest tests/unit/` y el linter.
2. Si cambiaste el esquema SQLite → bumpea `schema_version`, añade migración en `db.py`.
3. Si tocaste el formato DAT → ejecuta `pytest tests/validation/`.
4. Resume en el commit/PR **qué cambió** y **por qué** (no el *qué hace el código* — eso se ve en el diff).

---

## 11. Observabilidad

- Excepciones no controladas se loguean con contexto (fase, fichero, factura afectada).
- Toda exportación DAT queda registrada en `exportaciones`: fecha, rango, filtros JSON, nº facturas, ruta, SHA-256, versión de app. **Trazabilidad total no es opcional.**
- Logs JSON estructurado a fichero local rotado. Sin Sentry, sin telemetría externa en v1.0.

---

## 12. Glosario del dominio

| Término | Significado |
|---------|-------------|
| GESDAI | Software de facturación en FoxPro (origen de datos, **read-only**) |
| a3ASESOR | Software contable destino (consume `SUENLACE.DAT`) |
| Subcuenta | Cuenta contable de 6 dígitos. `430XXX` = clientes, `700/705/755 XXX` = ventas/ingresos |
| Mapping | Asociación revisada cliente/artículo → subcuenta (en SQLite) |
| Keyword | Regla con prioridad para resolver artículos no mapeados |
| Semáforo | 🟢 OK · 🟡 algún default/keyword · 🔴 bloqueante · ⚪ ya exportada |
| `cfactura.CONTABIL` | Campo de GESDAI — leído como aviso, **nunca** escrito |

---

## 13. Cosas que NO debes hacer

- Modificar GESDAI (ningún DBF, ningún campo, nunca).
- Commitear datos reales de COLVET.
- Usar `float` para importes.
- Hardcodear rutas o URLs.
- Importar `dbf_source.py` desde fuera de `sources/`.
- Silenciar excepciones con `except: pass`.
- Mostrar stack traces al usuario.
- Añadir dependencias para tareas triviales.
- Crear documentación nueva (`*.md`, READMEs) sin que el usuario lo pida.
- Asumir convenciones de otros proyectos Python — esta es una app de contabilidad para Windows con restricciones específicas.

---

## 14. Recursos

- [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md) — especificación funcional completa, fases, decisiones (D01–D09), modelo de datos, formato SUENLACE.
- [CLAUDE.md](CLAUDE.md) — instrucciones específicas para Claude Code (compatible con AGENTS.md, más detallado en flujo de trabajo).
- [README.md](README.md) — quick start para desarrolladores humanos.
