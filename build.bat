@echo off
REM Build del .exe autocontenido de gesdai-exporter.
REM Uso:
REM     build              -> build limpio (borra build\ y dist\)
REM     build keep         -> build sin limpiar (re-aprovecha cache)
REM     build analyse      -> solo analisis (PyInstaller sin --noconfirm, util para depurar imports)

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [build] No se encontro .venv. Ejecuta primero: dev install
    exit /b 1
)

call ".venv\Scripts\activate.bat"

REM Comprueba que PyInstaller esta disponible.
python -c "import PyInstaller" 1>nul 2>nul || (
    echo [build] PyInstaller no instalado en el venv. Ejecuta: dev install
    exit /b 1
)

if /I "%1"=="keep"    goto :icon
if /I "%1"=="analyse" goto :icon

echo [build] Limpiando build\ y dist\ ...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

:icon
echo [build] Generando icono .ico desde app\static\icon.svg ...
python scripts\build_icon.py
if errorlevel 1 (
    echo [build] AVISO: no se pudo generar el .ico. El build continua sin icono.
    echo [build]        Comprueba que PyMuPDF y Pillow estan instalados ^(dev install^).
    REM Si la generacion fallo, borramos cualquier .ico previo para que PyInstaller use icon=None.
    if exist app\static\icon.ico del /q app\static\icon.ico
)

if /I "%1"=="analyse" goto :analyse

echo [build] Generando .exe con PyInstaller ...
python -m PyInstaller --noconfirm gesdai_exporter.spec || goto :error

REM Copia .env.production junto al .exe si existe. Sin el, ProductionConfig
REM falla en _validate_production (SECRET_KEY) y el .exe muere al arrancar.
if exist ".env.production" (
    echo [build] Copiando .env.production a dist\gesdai_exporter\ ...
    copy /Y ".env.production" "dist\gesdai_exporter\.env.production" >nul
) else (
    echo [build] AVISO: .env.production no existe en la raiz del proyecto.
    echo [build]        El .exe arrancara en modo production y exigira SECRET_KEY.
    echo [build]        Crea .env.production a partir de .env.production.example.
)

echo.
echo [build] Listo. Carpeta de la app en: dist\gesdai_exporter\
echo [build] Lanzar con: dist\gesdai_exporter\gesdai_exporter.exe
goto :eof

:analyse
echo [build] Analisis (sin --noconfirm) ...
python -m PyInstaller gesdai_exporter.spec || goto :error
goto :eof

:error
echo [build] Error durante el build.
exit /b 1
