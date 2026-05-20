# gesdai-exporter

Herramienta local para COLVET Guadalajara que lee facturas de GESDAI (DBF/FoxPro), las convierte al formato `SUENLACE.DAT` de a3ASESOR y gestiona el mapeo cliente/artículo → subcuenta contable mediante una UI web embebida.

> **GESDAI siempre se abre en READ-ONLY.** Esta herramienta nunca modifica los DBF de origen.

Plan de desarrollo completo: [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md)
Convenciones para Claude Code: [CLAUDE.md](CLAUDE.md)

## Requisitos

- Python 3.11
- Windows (objetivo de despliegue)
- Acceso de lectura al directorio de DBFs de GESDAI (en producción: `C:\GESDAI\DATA`)

## Instalación (desarrollo)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
flask --app app run --debug
```

## Comandos

```bash
flask --app app run --debug              # servidor de desarrollo
python main.py                            # arranque como app de escritorio
pytest tests/unit/                        # tests unitarios rápidos
pytest --cov=app --cov-fail-under=85      # cobertura
pyinstaller gesdai_exporter.spec          # build del .exe
python scripts/generate_dev_data.py       # genera DBFs sintéticos
```

## Datos de desarrollo

Los DBFs sintéticos para tests viven en `tests/data/DATA_DEV/` y **nunca** se commitean. Genera tu propio set local con:

```bash
python scripts/generate_dev_data.py
```

## Estructura

Ver Sección 5 de [PLAN_DESARROLLO.md](PLAN_DESARROLLO.md).

## Licencia

Software interno de COLVET Guadalajara. Repositorio privado.
