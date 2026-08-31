#!/usr/bin/env python3
"""Build a native WaweKit desktop bundle and a shareable archive."""

from __future__ import annotations

import argparse
import hashlib
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
APP_NAME = "WaweKit"


def project_version() -> str:
    """Read the version without importing the application or GUI stack."""
    init_file = ROOT / "src" / "wawekit" / "__init__.py"
    for line in init_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("__version__ ="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"Could not find __version__ in {init_file}")


def architecture() -> str:
    """Return a stable architecture label for artifact filenames."""
    machine = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def run_pyinstaller() -> None:
    """Freeze the application for the current operating system."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is required. Install build dependencies with:\n"
            '    python -m pip install -e ".[gui]" pyinstaller'
        ) from exc

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(DIST),
        "--workpath",
        str(WORK),
        str(ROOT / "wawekit.spec"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)


def package_macos(version: str, arch: str) -> Path:
    """Create a compressed DMG containing the app and Applications link."""
    app = DIST / f"{APP_NAME}.app"
    if not app.is_dir():
        raise RuntimeError(f"Expected application bundle was not built: {app}")

    output = DIST / f"{APP_NAME}-{version}-macOS-{arch}.dmg"
    with tempfile.TemporaryDirectory(prefix="wawekit-dmg-", dir=WORK.parent) as temp:
        staging = Path(temp)
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        subprocess.run(
            [
                "hdiutil",
                "create",
                "-volname",
                f"{APP_NAME} {version}",
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                str(output),
            ],
            check=True,
        )
    return output


def package_windows(version: str, arch: str) -> Path:
    """Create a portable ZIP containing the Windows executable bundle."""
    bundle = DIST / APP_NAME
    if not (bundle / f"{APP_NAME}.exe").is_file():
        raise RuntimeError(f"Expected Windows executable was not built in {bundle}")
    base = DIST / f"{APP_NAME}-{version}-Windows-{arch}"
    return Path(shutil.make_archive(str(base), "zip", root_dir=DIST, base_dir=APP_NAME))


def package_linux(version: str, arch: str) -> Path:
    """Create a portable tarball containing the Linux executable bundle."""
    bundle = DIST / APP_NAME
    executable = bundle / APP_NAME
    if not executable.is_file():
        raise RuntimeError(f"Expected Linux executable was not built in {bundle}")
    output = DIST / f"{APP_NAME}-{version}-Linux-{arch}.tar.gz"
    with tarfile.open(output, "w:gz") as archive:
        archive.add(bundle, arcname=APP_NAME)
    return output


def write_checksum(artifact: Path) -> Path:
    """Write a SHA-256 checksum beside a release artifact."""
    digest = hashlib.sha256()
    with artifact.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    checksum = artifact.with_name(f"{artifact.name}.sha256")
    checksum.write_text(f"{digest.hexdigest()}  {artifact.name}\n", encoding="utf-8")
    return checksum


def main() -> int:
    """Build and package for the host platform."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle-only",
        action="store_true",
        help="run PyInstaller but do not create the DMG/ZIP/tar.gz",
    )
    args = parser.parse_args()

    run_pyinstaller()
    if args.bundle_only:
        return 0

    version = project_version()
    arch = architecture()
    system = platform.system()
    if system == "Darwin":
        artifact = package_macos(version, arch)
    elif system == "Windows":
        artifact = package_windows(version, arch)
    elif system == "Linux":
        artifact = package_linux(version, arch)
    else:
        raise SystemExit(f"Unsupported build platform: {system}")

    checksum = write_checksum(artifact)
    print(f"Built {artifact}")
    print(f"Checksum {checksum}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
