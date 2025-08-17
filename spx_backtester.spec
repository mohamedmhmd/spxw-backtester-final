# -*- mode: python ; coding: utf-8 -*-
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Make PyInstaller aggressively include PyQt6 & pandas bits
hiddenimports = []
hiddenimports += collect_submodules('PyQt6')
hiddenimports += collect_submodules('pandas')

datas = []
datas += collect_data_files('PyQt6', include_py_files=False)
datas += collect_data_files('pandas', include_py_files=False)

# If your project has non-Python assets (icons, qss, json, etc.) inside these packages,
# they will be picked up here. Otherwise it's harmless.
for pkg in ('engine', 'data', 'gui'):
    try:
        datas += collect_data_files(pkg, include_py_files=False)
    except Exception:
        pass

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SPX-0DTE-Backtester',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='SPX-0DTE-Backtester'
)
