@echo off
REM Arranque rapido del entorno de desarrollo.
REM Uso desde la terminal de VS Code:
REM     dev          -> arranca Flask en modo dev (hot-reload)
REM     dev test     -> pytest tests/unit/
REM     dev install  -> instala requirements + requirements-dev

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [dev] No se encontro .venv. Creando entorno virtual...
    python -m venv .venv || goto :error
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip || goto :error
    python -m pip install -r requirements.txt -r requirements-dev.txt || goto :error
) else (
    call ".venv\Scripts\activate.bat"
)

if /I "%1"=="test" (
    python -m pytest tests/unit/
    goto :eof
)

if /I "%1"=="install" (
    python -m pip install -r requirements.txt -r requirements-dev.txt
    goto :eof
)

python scripts\run_dev.py
goto :eof

:error
echo [dev] Error durante la inicializacion del entorno.
exit /b 1
