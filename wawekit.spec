"""PyInstaller build specification for the WaweKit desktop application."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH)
APP_NAME = "WaweKit"


def project_version():
    """Read the package version without importing the GUI application."""
    init_file = ROOT / "src/wawekit/__init__.py"
    for line in init_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ ="):
            return line.split("=", 1)[1].strip().strip('"\'')
    raise RuntimeError(f"Could not find __version__ in {init_file}")


APP_VERSION = project_version()

# Assets loaded through importlib.resources and configuration loaded by path.
datas = [
    (str(ROOT / "src/wawekit/resources/icons"), "wawekit/resources/icons"),
    (str(ROOT / "src/wawekit/resources/web"), "wawekit/resources/web"),
    (str(ROOT / "src/wawekit/resources/manual"), "wawekit/resources/manual"),
    (str(ROOT / "src/wawekit/gui/themes"), "wawekit/gui/themes"),
    (str(ROOT / "config/default_settings.toml"), "config"),
    (str(ROOT / "LICENSE"), "."),
]

# RDKit's C++ extensions load package data by filesystem path at runtime.
datas += collect_data_files("rdkit")

# These packages discover extension modules or backends dynamically.
hiddenimports = (
    collect_submodules("rdkit.Chem")
    + collect_submodules("sklearn")
    + ["matplotlib.backends.backend_qtagg"]
)

analysis = Analysis(
    [str(ROOT / "src/wawekit/__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(
        ROOT
        / "src/wawekit/resources/icons"
        / ("wawekit.icns" if sys.platform == "darwin" else "wawekit.ico")
    ),
)

bundle_contents = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

# BUNDLE turns the collected directory into a Finder-launchable .app. Other
# platforms use the collected directory directly (containing WaweKit.exe on
# Windows and WaweKit on Linux).
if sys.platform == "darwin":
    app = BUNDLE(
        bundle_contents,
        name=f"{APP_NAME}.app",
        icon=str(ROOT / "src/wawekit/resources/icons/wawekit.icns"),
        bundle_identifier="com.thewaweai.wawekit",
        info_plist={
            "CFBundleDisplayName": APP_NAME,
            "CFBundleName": APP_NAME,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "NSHighResolutionCapable": True,
        },
    )
