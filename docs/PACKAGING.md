# Building installable desktop releases

WaweKit uses PyInstaller to bundle Python, Qt, RDKit, and the application assets.
End users do not need Python or any packages installed.

PyInstaller is not a cross-compiler. Build each artifact on the operating system
where it will run, or use the included GitHub Actions release workflow.

## Local build

Create and activate a Python 3.12 virtual environment, then run:

```bash
python -m pip install -e ".[gui]" pyinstaller
python scripts/build_release.py
```

The command creates the native bundle and its shareable archive:

| Build host | Output |
| --- | --- |
| macOS Apple Silicon | `dist/WaweKit.app` and `dist/WaweKit-0.1.0-macOS-arm64.dmg` |
| macOS Intel | `dist/WaweKit.app` and `dist/WaweKit-0.1.0-macOS-x86_64.dmg` |
| Windows | `dist/WaweKit/WaweKit.exe` and a portable `.zip` |
| Linux | `dist/WaweKit/WaweKit` and a portable `.tar.gz` |

Each archive also gets a neighboring `.sha256` checksum file.

On macOS, open the DMG and drag WaweKit into the Applications shortcut. The
artifact is architecture-specific: an Apple Silicon build does not support an
Intel-only Mac. A universal build requires a universal Python plus universal
versions of every compiled dependency, including RDKit and Qt.

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
- Sign `WaweKit.exe` (and any later Windows installer) with an Authenticode code
  signing certificate.
- Publish checksums beside every download.

Certificates and credentials must be stored as encrypted CI secrets, never in
the repository. Signing is intentionally not faked with ad-hoc credentials.

## Smoke test

Always test the frozen application itself, not `python -m wawekit`:

1. Launch the installed application and confirm the splash, theme, and icons.
2. Load a sample SMILES/SDF file and compute descriptors.
3. Open a chart such as Chemical Space.
4. Generate and inspect a 3D conformer.
5. Export a report and reopen the application to verify user settings.

These checks cover packaged resources, RDKit data, matplotlib's Qt backend,
QtWebEngine/3Dmol.js, filesystem permissions, and native compiled libraries.
