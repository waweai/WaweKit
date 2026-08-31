# Packaging WaweKit as a desktop bundle

WaweKit is normally run from source (`pip install -e ".[gui]"` then `wawekit`).
For end users who should not need a Python environment, `wawekit.spec` freezes
the app into a self-contained bundle with
[PyInstaller](https://pyinstaller.org/) — Python, Qt, RDKit and every
application asset included.

PyInstaller is not a cross-compiler. Build each artifact on the operating system
where it will run, or use the included GitHub Actions release workflow.

## Local build

Create and activate a Python 3.12 virtual environment, then run:

```bash
python -m pip install -e ".[gui]" pyinstaller
python scripts/build_release.py
```

`scripts/build_release.py` freezes the app and then packages the result the way
that platform's users expect:

| Build host | Output |
| --- | --- |
| macOS Apple Silicon | `dist/WaweKit.app` and `dist/WaweKit-0.1.0-macOS-arm64.dmg` |
| macOS Intel | `dist/WaweKit.app` and `dist/WaweKit-0.1.0-macOS-x86_64.dmg` |
| Windows | `dist/WaweKit/WaweKit.exe` and a portable `.zip` |
| Linux | `dist/WaweKit/WaweKit` and a portable `.tar.gz` |

Each archive gets a neighbouring `.sha256` checksum file. Pass `--bundle-only`
to run PyInstaller without producing the archive.

On macOS, open the DMG and drag WaweKit into the Applications shortcut. The
artifact is architecture-specific: an Apple Silicon build does not support an
Intel-only Mac. A universal build requires a universal Python plus universal
versions of every compiled dependency, including RDKit and Qt.

## Why a hand-written `.spec` file

A plain `pyinstaller src/wawekit/app.py` looks like it should work — PyInstaller
walks the import graph and bundles what it finds — but three categories of files
never appear in that graph and would silently be missing from the frozen build:

1. **Assets loaded by path, not `import`.** The SVG toolbar icons and PNG brand
   assets (`resources/icons/`), the two QSS theme sheets
   (`gui/themes/{dark,light}.qss`), the vendored `3Dmol-min.js` used by the 3D
   conformer viewer, and the illustrated user manual (`resources/manual/`) are
   all read via `importlib.resources` at runtime. PyInstaller's static analysis
   only sees `import` statements, so these are listed explicitly in the spec's
   `datas`.
2. **RDKit's own data files.** RDKit's C++ layer loads atomic parameter tables
   (used by standardization and descriptor calculation) from files inside the
   installed `rdkit` package, not via Python `import`. The spec uses
   `collect_data_files("rdkit")` to pull all of it in rather than guessing which
   files are load-bearing.
3. **Dynamically imported compiled submodules.** RDKit, scikit-learn, and
   matplotlib's Qt backend (`matplotlib.backends.backend_qtagg`, needed by every
   embedded chart) are imported in ways PyInstaller's static graph walk doesn't
   always catch. Listed explicitly under `hiddenimports`.

The spec reads the version straight out of `src/wawekit/__init__.py`, so the
frozen bundle can never disagree with the package about what it is.

## Deliberate choices

- **`--onefile` is not used.** A single-exe build has to self-extract to a temp
  directory on every launch, which is slow and awkward for an app this size
  (RDKit + Qt + scikit-learn + matplotlib). A folder build starts instantly and
  is the standard approach for scientific desktop apps.
- **UPX compression is disabled** (`upx=False`). Compressing Qt/RDKit's compiled
  binaries with UPX is a well-known source of both false-positive antivirus
  flags and startup crashes on Windows. The size savings are not worth either
  risk.
- **The app icon is the WaweKit badge.** `resources/icons/wawekit.ico` is a
  multi-resolution (16–256 px) Windows icon generated from the brand logo
  (`WaweKit.png` at the repo root), and `resources/icons/wawekit.icns` is its
  macOS counterpart, used by the `.app` bundle.

## Windows installer (desktop icon)

`dist/WaweKit/` is a folder the user would otherwise have to keep somewhere and
launch by hand. `packaging/windows/wawekit.iss` wraps it in an
[Inno Setup](https://jrsoftware.org/isinfo.php) installer so installing behaves
the way people expect from a desktop app:

```bash
python scripts/build_release.py --bundle-only   # 1. freeze  -> dist/WaweKit/
iscc packaging/windows/wawekit.iss              # 2. package -> dist/installer/WaweKitSetup-0.1.0.exe
```

What the installer does:

- **A desktop icon**, from a *Create a desktop icon* checkbox that is ticked by
  default — the point of the whole step.
- A Start Menu group with the app and its uninstaller.
- An Add/Remove Programs entry that uninstalls cleanly. The stable `AppId` GUID
  means the next version upgrades this install rather than sitting beside it —
  never reuse that GUID for another app.
- Registers `.sdf` / `.smi` / `.mol` under an "Open with" ProgId, so molecule
  files show the WaweKit icon and can be opened by double-click.
- Installs **per-user** (`PrivilegesRequired=lowest`) into `%LOCALAPPDATA%`,
  which needs no admin rights — the common case on managed lab machines.
  `WaweKitSetup.exe /ALLUSERS` still gives a machine-wide install.
- Writes the same `.desktop-shortcut` marker file the application uses (see
  below), so a user who *unticks* the desktop-icon box does not get one anyway
  the first time they launch.

User settings and logs under `%APPDATA%\TheWaweAI\WaweKit` are deliberately left
in place by the uninstaller.

## Shortcuts for a `pip` install

A PEP 517 wheel has no post-install hook, so `pip install "wawekit[gui]"` cannot
place an icon at install time. `wawekit.core.shortcut` covers that route
instead: the first launch creates the desktop icon and menu entry, then drops a
marker file in the config directory so it never asks again — deleting the icon
has to mean deleting it. The same code is exposed as the `wawekit-shortcut`
console script (`--remove`, `--no-menu`) and as
`Help → Create Desktop Shortcut`.

The module is deliberately Qt-free and uses only the standard library: a `.lnk`
written through `WScript.Shell` under PowerShell on Windows, an XDG `.desktop`
entry on Linux (installed both to the desktop and to
`~/.local/share/applications`), and a symlink to the `.app` — or an executable
`.command` — on macOS. `pywin32` is not worth taking on as a dependency for one
shortcut, and hand-writing the binary `.lnk` format is far more fragile than
driving the COM object Windows already ships.

## Automated builds for all operating systems

The `Build desktop releases` workflow can be run manually from the repository's
Actions tab. It builds macOS, Windows, and Linux artifacts in parallel and makes
them downloadable from that workflow run.

Pushing a version tag also creates a GitHub release and attaches all artifacts:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Keep the tag, `project.version` in `pyproject.toml`, and `__version__` in
`src/wawekit/__init__.py` synchronized. The build reads the artifact version
from `__version__` automatically.

## Signing before public distribution

The generated artifacts are unsigned development builds. They are suitable for
testing and direct sharing, but macOS Gatekeeper and Windows SmartScreen warn
users about software from an unidentified developer.

For a public release:

- Sign the `.app` with an Apple Developer ID Application certificate, sign the
  DMG, submit it to Apple's notary service, and staple the notarization ticket.
- Sign `WaweKit.exe` and the Inno Setup installer with an Authenticode code
  signing certificate.
- Publish checksums beside every download.

Certificates and credentials must be stored as encrypted CI secrets, never in
the repository. Signing is intentionally not faked with ad-hoc credentials.

Auto-update is out of scope for v1.

## Verifying a build

Always test the frozen application itself, not `python -m wawekit`. Launch the
built app directly and confirm:

1. The main window opens and the splash, theme and icons render (proves the
   `datas` bundling worked).
2. Loading a sample `.smi`/`.sdf` file and computing descriptors works (proves
   RDKit's data files and hidden imports are present).
3. A chart such as Chemical Space or the Reproducibility panel opens (proves the
   matplotlib Qt backend was bundled).
4. The 3D conformer viewer renders (proves `3Dmol-min.js` and QtWebEngine are
   present).
5. Exporting a report and reopening the application preserves user settings
   (proves filesystem permissions and the config directory).
6. On Windows, running the installer produces a desktop icon that shows the
   WaweKit badge and launches the app (proves the `.iss` `[Icons]`/`[Tasks]`
   wiring and the bundled `.ico`).

This is a full smoke test of every category of asset the hand-written spec
exists to bundle — a build that merely "doesn't error during `pyinstaller`" is
not sufficient proof, since missing data files fail at runtime, not build time.
