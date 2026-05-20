# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — build .exe autocontenido para Windows.
# Uso: pyinstaller gesdai_exporter.spec
#
# Notas:
#   - Los blueprints (`app.routes.*`) y las fuentes (`app.sources.*`) se
#     importan dentro de funciones — PyInstaller no los detecta por análisis
#     estático, así que usamos `collect_submodules` para forzar su inclusión.
#   - UPX desactivado: no se asume binario disponible en el sistema; además
#     reduce poco en .exe ya comprimido y dispara falsos positivos de AV.
#   - `console=True` durante la fase de smoke testing del .exe. Cuando el
#     arranque sea estable, cambiar a `False` para entregar al usuario final.

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

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
        'tkinter',     # no se usa
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='gesdai_exporter',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
