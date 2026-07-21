# Packaging Wawekit as a desktop bundle

Wawekit is normally run from source (`pip install -e .` then `wawekit`, or
`python -m wawekit`). For end users who should not need a Python environment,
`wawekit.spec` freezes the app into a self-contained folder with
[PyInstaller](https://pyinstaller.org/).

## Building

```bash
pip install -e ".[dev]"        # includes pyinstaller
pyinstaller wawekit.spec
```

Output: `dist/Wawekit/` — a folder containing `Wawekit.exe` (Windows) or
`Wawekit` (Linux/macOS) plus all bundled libraries and data files. Distribute
the whole folder; the executable is not standalone (`--onefile` is
deliberately not used — see below).

## Why a hand-written `.spec` file

A plain `pyinstaller src/wawekit/app.py` looks like it should work — PyInstaller
walks the import graph and bundles what it finds — but three categories of
files never appear in that graph and would silently be missing from the
frozen build:

1. **Assets loaded by path, not `import`.** The SVG toolbar icons and PNG
   brand assets (`resources/icons/`), the two QSS theme sheets
   (`gui/themes/{dark,light}.qss`), the vendored `3Dmol-min.js` used by the
   3D conformer viewer (Module 9), and the illustrated user manual
   (`resources/manual/`) are all read via `importlib.resources` at
   runtime. PyInstaller's static analysis only sees `import` statements, so
   these are listed explicitly in the spec's `datas`.
2. **RDKit's own data files.** RDKit's C++ layer loads atomic parameter
   tables (used by standardization and descriptor calculation) from files
   inside the installed `rdkit` package, not via Python `import`. The spec
   uses `collect_data_files("rdkit")` to pull all of it in rather than
   guessing which files are load-bearing.
3. **Dynamically imported compiled submodules.** RDKit, scikit-learn, and
   matplotlib's Qt backend (`matplotlib.backends.backend_qtagg`, needed by
   every embedded chart — Modules 10, 11, and the reproducibility panel) are
   imported in ways PyInstaller's static graph walk doesn't always catch.
   Listed explicitly under `hiddenimports`.

## Deliberate choices

- **`--onefile` is not used.** A single-exe build has to self-extract to a
  temp directory on every launch, which is slow and awkward for an app this
  size (RDKit + Qt + scikit-learn + matplotlib). A folder build starts
  instantly and is the standard approach for scientific desktop apps.
- **UPX compression is disabled** (`upx=False`). Compressing Qt/RDKit's
  compiled binaries with UPX is a well-known source of both false-positive
  antivirus flags and startup crashes on Windows. The size savings are not
  worth either risk.
- **The app icon is the WaweKit badge.** `resources/icons/wawekit.ico` is a
  multi-resolution (16–256 px) Windows icon generated from the brand logo
  (`WaweKit.png` at the repo root); the spec points `icon=` at it. A macOS
  `.icns` would still need generating for a Mac build.

## What is *not* covered here

- Code signing (Windows Authenticode / macOS notarization) — required before
  any real public distribution, since an unsigned executable triggers OS
  warnings. Left for Module 20 release prep, since it needs real certificates.
- An installer (MSI/NSIS on Windows, `.dmg` on macOS, AppImage on Linux) —
  the `dist/Wawekit/` folder from this spec is the *input* to that step, not
  a replacement for it.
- Auto-update. Out of scope for v1.

## Verifying a build

After `pyinstaller wawekit.spec`, launch `dist/Wawekit/Wawekit.exe` directly
(not through Python) and confirm:

- The main window opens and the theme/icons render (proves the `datas`
  bundling worked).
- Load a sample `.smi`/`.sdf` file and compute descriptors (proves RDKit's
  data files and hidden imports are present).
- Open the Chemical Space or Reproducibility panel (proves the matplotlib Qt
  backend was bundled).
- Open the 3D conformer viewer (proves `3Dmol-min.js` and QtWebEngine are
  present).

This is a full smoke test of every category of asset the hand-written spec
exists to bundle — a build that merely "doesn't error during `pyinstaller`"
is not sufficient proof, since missing data files fail at runtime, not build
time.
