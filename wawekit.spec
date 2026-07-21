# PyInstaller build spec for Wawekit (Module 17).
#
# Build with:  pyinstaller wawekit.spec
# Output:      dist/Wawekit/Wawekit.exe (Windows) or dist/Wawekit/Wawekit (Linux/macOS)
#
# Why a hand-written .spec instead of a one-line `pyinstaller src/wawekit/app.py`
# --------------------------------------------------------------------------
# Three things Wawekit ships that PyInstaller cannot infer on its own:
#   1. Non-Python DATA FILES the app reads via importlib.resources at runtime:
#      SVG icons, QSS themes, and the vendored 3Dmol.js (Module 9). None of
#      these are imported, so PyInstaller's import-graph analysis never finds
#      them — they must be listed explicitly or the frozen app ships broken.
#   2. QtWebEngine (Module 9's 3D viewer) needs its own resource/locale/process
#      files alongside the executable; PySide6's own hook usually handles this,
#      but we pin it here so a version regression fails the build loudly
#      instead of shipping a silently-broken 3D tab.
#   3. RDKit, scikit-learn and matplotlib all import compiled extension
#      submodules dynamically (not via a plain `import`), which PyInstaller's
#      static analysis misses — hence the explicit hiddenimports below.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# --- 1. Non-Python assets read via importlib.resources at runtime ----------
datas = [
    ("src/wawekit/resources/icons", "wawekit/resources/icons"),
    ("src/wawekit/resources/web", "wawekit/resources/web"),
    ("src/wawekit/resources/manual", "wawekit/resources/manual"),
    ("src/wawekit/gui/themes/dark.qss", "wawekit/gui/themes"),
    ("src/wawekit/gui/themes/light.qss", "wawekit/gui/themes"),
    ("config/default_settings.toml", "config"),
]
# RDKit ships its own data (atomic parameter files for standardization,
# fingerprints, etc.) that rdkit's C++ layer loads by path at import time.
datas += collect_data_files("rdkit")

# --- 2. Compiled extension submodules static analysis cannot see -----------
hiddenimports = (
    collect_submodules("rdkit.Chem")
    + collect_submodules("sklearn")
    + ["matplotlib.backends.backend_qtagg"]
)

a = Analysis(
    ["src/wawekit/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],  # never used; keeps the frozen bundle smaller
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
    name="Wawekit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-compressing Qt/RDKit binaries is a frequent source of
    # false-positive antivirus flags and startup crashes; not worth the size win.
    console=False,  # a GUI app: no terminal window on launch
    # Multi-resolution .ico generated from the WaweKit badge (WaweKit.png).
    icon="src/wawekit/resources/icons/wawekit.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Wawekit",
)
