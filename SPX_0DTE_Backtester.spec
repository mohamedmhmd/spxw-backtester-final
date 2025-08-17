# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Hidden imports: add explicit packages
hidden = ['PyQt6', 'matplotlib', 'pandas', 'numpy', 'aiohttp']

# Collect all SciPy + NumPy submodules and data files
hidden += collect_submodules('scipy') + collect_submodules('numpy')
datas = [('*.py', '.'), *collect_data_files('scipy'), *collect_data_files('numpy')]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    name='SPX_0DTE_Backtester',
    console=False,   # no console window
    icon=None,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name='SPX_0DTE_Backtester'
)
