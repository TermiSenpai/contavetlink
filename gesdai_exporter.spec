# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — build .exe en formato carpeta (onedir) para Windows.
# Uso: pyinstaller gesdai_exporter.spec
#
# Salida:
#   dist\gesdai_exporter\
#       gesdai_exporter.exe       <- ejecutable
#       .env.production           <- copiar manualmente o automatizar tras el build
#       _internal\                <- DLLs, Python runtime, templates/, static/, deps
#
# Por qué onedir (no onefile):
#   - Arranque instantáneo (sin extracción a %TEMP%\_MEIxxxxx).
#   - .env.production puede vivir junto al .exe y se edita en sitio.
#   - Menos falsos positivos de antivirus.
#   - Logs, .db y exports siguen en %APPDATA%\GesdaiExporter\ — la carpeta
#     del .exe se puede reemplazar entera en una actualización sin perder datos.
#
# Notas:
#   - Los blueprints (`app.routes.*`) y las fuentes (`app.sources.*`) se
#     importan dentro de funciones — PyInstaller no los detecta por análisis
#     estático, así que usamos `collect_submodules` para forzar su inclusión.
#   - UPX desactivado: no se asume binario disponible y dispara falsos positivos.
#   - `console=True` durante la fase de smoke testing del .exe. Cuando el
#     arranque sea estable, cambiar a `False` para entregar al usuario final.

import os

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Icono del .exe: generado por scripts/build_icon.py desde app/static/icon.svg
# (build.bat lo invoca antes de PyInstaller). Si no existe, dejamos icon=None
# para que el build no se rompa por una dependencia opcional de rasterizado.
_icon_path = os.path.join('app', 'static', 'icon.ico')
APP_ICON = _icon_path if os.path.isfile(_icon_path) else None

hiddenimports = []
hiddenimports += collect_submodules('app')        # routes/, sources/, mapping/, exporter/, io/
hiddenimports += collect_submodules('updater')
hiddenimports += [
    'dbf',
    'aenum',          # dependencia interna de `dbf`
    'openpyxl',
    'et_xmlfile',     # dependencia interna de `openpyxl`
    'flask',
    'jinja2',
    'werkzeug',
    'click',
    'itsdangerous',
    'blinker',
    'markupsafe',
    'requests',
    'urllib3',
    'certifi',
    'charset_normalizer',
    'idna',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('app/templates', 'app/templates'),
        ('app/static', 'app/static'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'pytest',
        'coverage',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='gesdai_exporter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=APP_ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='gesdai_exporter',
)
