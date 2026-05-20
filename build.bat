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

if /I "%1"=="keep" goto :build
if /I "%1"=="analyse" goto :analyse

echo [build] Limpiando build\ y dist\ ...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist

:build
echo [build] Generando .exe con PyInstaller ...
python -m PyInstaller --noconfirm gesdai_exporter.spec || goto :error

echo.
echo [build] Listo. Binario en: dist\gesdai_exporter.exe
goto :eof

:analyse
echo [build] Analisis (sin --noconfirm) ...
python -m PyInstaller gesdai_exporter.spec || goto :error
goto :eof

:error
echo [build] Error durante el build.
exit /b 1
