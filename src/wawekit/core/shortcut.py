r"""Desktop (and Start Menu) shortcut creation.

Installing Wawekit should leave the user with something to double-click. How
that happens differs per install route, so this module is the single place that
knows *how* to make a shortcut, and the three routes all call into it:

* ``pip install "wawekit[gui]"`` — no post-install hook exists in modern
  (PEP 517) wheels, so the first launch of the app creates the shortcut
  (:func:`create_on_first_run`), and ``wawekit-shortcut`` re-creates or removes
  it on demand.
* The frozen build — the Windows installer (``packaging/windows/wawekit.iss``)
  creates the icons itself, which is why first-run creation is skipped when
  the app is running from an installed bundle that already has one.
* Manually — ``wawekit-shortcut`` / Help ▸ *Create Desktop Shortcut*.

Deliberately Qt-free
--------------------
Everything here uses only the standard library, so ``wawekit-shortcut`` works
in a headless install and this module can be imported before the GUI stack is
loaded. That is also why the user directories are resolved here (registry /
XDG) rather than through :mod:`wawekit.core.paths`, which needs
``QStandardPaths``.

Per-platform mechanism
----------------------
Windows
    A real ``.lnk``, written through the ``WScript.Shell`` COM object driven by
    PowerShell. Writing the binary ``.lnk`` format by hand is the only
    dependency-free alternative and is far more fragile; ``pywin32`` is not a
    dependency we want for one shortcut.
Linux
    An XDG ``.desktop`` entry, installed both into
    ``~/.local/share/applications`` (so it appears in the application menu and
    launcher search) and onto the desktop, marked executable.
macOS
    A symlink to the ``.app`` bundle when frozen, otherwise an executable
    ``.command`` launcher — macOS has no shortcut format for "run this command"
    short of building a bundle.

Every entry point is best-effort and idempotent: a shortcut that cannot be
created is a logged warning, never a crash, and creating one twice just
overwrites it.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path

from wawekit.core import constants

logger = logging.getLogger(__name__)

#: Base name of the shortcut file (extension added per platform).
_SHORTCUT_STEM = constants.APP_NAME

#: Marker written next to the user config after first-run creation is attempted.
#: Its presence — success or failure — stops the app retrying on every launch;
#: a user who deleted the shortcut on purpose should not have it come back.
_MARKER_NAME = ".desktop-shortcut"


class ShortcutError(RuntimeError):
    """Raised when a shortcut could not be created or removed."""


# --------------------------------------------------------------------------
# Locations
# --------------------------------------------------------------------------
def _windows_shell_folder(key: str) -> Path | None:
    """Return a Windows shell folder from the registry, or ``None``.

    The registry is consulted rather than assuming ``~/Desktop`` because both
    OneDrive-backed and roaming profiles relocate the real Desktop, and a
    shortcut written to the wrong one is invisible to the user.
    """
    try:
        import winreg

        subkey = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as handle:
            raw, _ = winreg.QueryValueEx(handle, key)
    except (ImportError, OSError):
        return None
    path = Path(os.path.expandvars(raw))
    return path if path.is_dir() else None


def _xdg_desktop_dir() -> Path | None:
    """Return the desktop directory from ``user-dirs.dirs`` (localized names)."""
    config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    user_dirs = config / "user-dirs.dirs"
    if not user_dirs.is_file():
        return None
    try:
        for line in user_dirs.read_text(encoding="utf-8").splitlines():
            if not line.startswith("XDG_DESKTOP_DIR"):
                continue
            value = line.split("=", 1)[1].strip().strip('"')
            path = Path(os.path.expandvars(value.replace("$HOME", str(Path.home()))))
            return path if path.is_dir() else None
    except (OSError, IndexError):
        return None
    return None


def desktop_dir() -> Path | None:
    """Return the user's desktop directory, or ``None`` if there is not one.

    A missing desktop directory is normal (headless servers, some Linux
    desktops), and callers treat it as "nothing to do" rather than an error.
    """
    if sys.platform == "win32":
        found = _windows_shell_folder("Desktop")
        if found is not None:
            return found
    elif sys.platform.startswith("linux"):
        found = _xdg_desktop_dir()
        if found is not None:
            return found
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def _start_menu_dir() -> Path | None:
    """Return the per-user Start Menu *Programs* folder (Windows only)."""
    if sys.platform != "win32":
        return None
    return _windows_shell_folder("Programs")


def state_dir() -> Path:
    """Return the directory holding the first-run marker.

    Mirrors what :func:`wawekit.core.paths.config_dir` returns, computed without
    Qt so the CLI can find the same marker the application writes.
    """
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / constants.ORG_NAME / constants.APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / constants.APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / constants.ORG_NAME / constants.APP_NAME


# --------------------------------------------------------------------------
# What the shortcut points at
# --------------------------------------------------------------------------
def _pythonw() -> str:
    """Return the windowless interpreter on Windows, else :data:`sys.executable`.

    Launching the app through ``python.exe`` leaves a console window open
    behind the GUI for the whole session; ``pythonw.exe`` sits next to it in
    every CPython install and does not.
    """
    if sys.platform != "win32":
        return sys.executable
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return str(candidate) if candidate.is_file() else sys.executable


def launcher_command() -> list[str]:
    """Return the command a shortcut should run, as ``[program, *args]``.

    Three cases, in priority order: a frozen bundle launches its own
    executable; a normal install prefers the ``wawekit`` console script created
    by pip (it is on the user's PATH and survives the venv being moved less
    badly than a raw interpreter path); otherwise fall back to
    ``python -m wawekit``.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    if sys.platform == "win32":
        # Prefer pythonw over wawekit.exe: the console script is a console
        # binary, so a shortcut to it flashes (and keeps) a terminal window.
        return [_pythonw(), "-m", constants.APP_SLUG]
    script = shutil.which(constants.APP_SLUG)
    if script:
        return [script]
    return [sys.executable, "-m", constants.APP_SLUG]


def _icon_file() -> Path | None:
    """Return a filesystem path to the app icon for this platform, or ``None``.

    ``.ico`` on Windows (multi-resolution, what ``.lnk`` wants), the PNG badge
    elsewhere. When the package is imported from a zip the asset is copied out
    to the state directory, since a shortcut needs a real path on disk.
    """
    name = "icons/wawekit.ico" if sys.platform == "win32" else "icons/wawekit_badge.png"
    try:
        traversable = resources.files("wawekit.resources").joinpath(name)
        direct = Path(str(traversable))
        if direct.is_file():
            return direct
        extracted = state_dir() / Path(name).name
        extracted.parent.mkdir(parents=True, exist_ok=True)
        extracted.write_bytes(traversable.read_bytes())
        return extracted
    except (OSError, ModuleNotFoundError, TypeError):
        logger.debug("No icon asset available for the shortcut", exc_info=True)
        return None


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------
def _ps_quote(value: str) -> str:
    """Quote a string as a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def _run_powershell(script: str) -> None:
    """Run ``script`` with PowerShell, raising :class:`ShortcutError` on failure.

    ``-ExecutionPolicy Bypass`` applies to this process only and is what makes
    this work on locked-down machines where the default policy is Restricted;
    it is not a persistent change to the user's system.
    """
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        raise ShortcutError("PowerShell was not found; cannot create a Windows shortcut.")
    try:
        result = subprocess.run(  # noqa: S603 — fixed program, no shell
            [
                powershell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(f"Could not run PowerShell: {exc}") from exc
    if result.returncode != 0:
        raise ShortcutError((result.stderr or result.stdout).strip() or "PowerShell failed.")


def _write_windows_lnk(target: Path) -> Path:
    """Create a ``.lnk`` at ``target`` pointing at the app, and return it."""
    program, *args = launcher_command()
    icon = _icon_file()
    lines = [
        "$shell = New-Object -ComObject WScript.Shell",
        f"$lnk = $shell.CreateShortcut({_ps_quote(str(target))})",
        f"$lnk.TargetPath = {_ps_quote(program)}",
        f"$lnk.Arguments = {_ps_quote(subprocess.list2cmdline(args))}",
        f"$lnk.WorkingDirectory = {_ps_quote(str(Path(program).parent))}",
        f"$lnk.Description = {_ps_quote(constants.APP_DESCRIPTION)}",
    ]
    if icon is not None:
        lines.append(f"$lnk.IconLocation = {_ps_quote(f'{icon},0')}")
    lines.append("$lnk.Save()")
    _run_powershell("; ".join(lines))
    if not target.is_file():
        raise ShortcutError(f"PowerShell reported success but {target} was not created.")
    return target


# --------------------------------------------------------------------------
# Linux
# --------------------------------------------------------------------------
def _desktop_entry_text() -> str:
    """Return the contents of the XDG ``.desktop`` entry."""
    exec_line = " ".join(_shell_quote(part) for part in launcher_command())
    icon = _icon_file()
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Version={constants.APP_VERSION}",
        f"Name={constants.APP_NAME}",
        f"Comment={constants.APP_DESCRIPTION}",
        f"Exec={exec_line}",
        "Terminal=false",
        # Lets the desktop match the running Qt window to this launcher, so the
        # taskbar shows one pinned entry rather than a duplicate generic icon.
        f"StartupWMClass={constants.APP_NAME}",
        "Categories=Science;Chemistry;Education;",
        "Keywords=cheminformatics;chemistry;molecules;RDKit;",
    ]
    if icon is not None:
        lines.append(f"Icon={icon}")
    return "\n".join(lines) + "\n"


def _shell_quote(value: str) -> str:
    """Quote one argument for a ``.desktop`` ``Exec=`` line."""
    return value if value and all(c.isalnum() or c in "-_./" for c in value) else f'"{value}"'


def _write_desktop_entry(target: Path) -> Path:
    """Write an executable ``.desktop`` file at ``target`` and return it."""
    target.write_text(_desktop_entry_text(), encoding="utf-8")
    target.chmod(0o755)
    # GNOME (and Cinnamon) refuse to launch a desktop-folder .desktop file
    # unless it is marked trusted; failure here is fine — the user can still
    # right-click ▸ Allow Launching.
    gio = shutil.which("gio")
    if gio:
        try:
            subprocess.run(  # noqa: S603 — resolved program, no shell
                [gio, "set", str(target), "metadata::trusted", "true"],
                capture_output=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("Could not mark %s trusted", target, exc_info=True)
    return target


def _install_application_entry() -> Path | None:
    """Install the ``.desktop`` entry into the user's application menu."""
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "applications"
    try:
        apps.mkdir(parents=True, exist_ok=True)
        entry = _write_desktop_entry(apps / f"{constants.APP_SLUG}.desktop")
    except OSError:
        logger.debug("Could not install the application-menu entry", exc_info=True)
        return None
    update = shutil.which("update-desktop-database")
    if update:
        try:
            subprocess.run(  # noqa: S603 — resolved program, no shell
                [update, str(apps)], capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("update-desktop-database failed", exc_info=True)
    return entry


# --------------------------------------------------------------------------
# macOS
# --------------------------------------------------------------------------
def _macos_app_bundle() -> Path | None:
    """Return the enclosing ``.app`` bundle when frozen inside one."""
    if not getattr(sys, "frozen", False):
        return None
    for parent in Path(sys.executable).resolve().parents:
        if parent.suffix == ".app":
            return parent
    return None


def _write_macos_launcher(directory: Path) -> Path:
    """Create a Desktop launcher on macOS and return it.

    A symlink to the ``.app`` when one exists (double-clicking it launches the
    bundle with its own icon); otherwise an executable ``.command`` script,
    which is the only thing Finder will run directly without building a bundle.
    """
    bundle = _macos_app_bundle()
    if bundle is not None:
        link = directory / bundle.name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(bundle)
        return link

    command = " ".join(_shell_quote(part) for part in launcher_command())
    target = directory / f"{_SHORTCUT_STEM}.command"
    target.write_text(f"#!/bin/sh\nexec {command}\n", encoding="utf-8")
    target.chmod(0o755)
    return target


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def shortcut_path() -> Path | None:
    """Return where the desktop shortcut lives, or ``None`` without a desktop."""
    directory = desktop_dir()
    if directory is None:
        return None
    if sys.platform == "win32":
        return directory / f"{_SHORTCUT_STEM}.lnk"
    if sys.platform == "darwin":
        bundle = _macos_app_bundle()
        return directory / (bundle.name if bundle else f"{_SHORTCUT_STEM}.command")
    return directory / f"{constants.APP_SLUG}.desktop"


def create_desktop_shortcut(start_menu: bool = True) -> list[Path]:
    """Create the desktop shortcut (and menu entry) and return what was written.

    Parameters
    ----------
    start_menu:
        Also register the app with the system menu — the Start Menu on Windows,
        the application menu on Linux. Ignored on macOS.

    Returns
    -------
    list[pathlib.Path]
        Every file created, desktop entry first. Empty if the machine has no
        desktop directory.

    Raises
    ------
    ShortcutError
        If a shortcut was attempted and failed.

    """
    created: list[Path] = []
    target = shortcut_path()

    if target is not None:
        try:
            if sys.platform == "win32":
                created.append(_write_windows_lnk(target))
            elif sys.platform == "darwin":
                created.append(_write_macos_launcher(target.parent))
            else:
                created.append(_write_desktop_entry(target))
        except OSError as exc:
            raise ShortcutError(f"Could not write {target}: {exc}") from exc
    else:
        logger.info("No desktop directory found; skipping the desktop shortcut.")

    if start_menu:
        if sys.platform == "win32":
            programs = _start_menu_dir()
            if programs is not None:
                created.append(_write_windows_lnk(programs / f"{_SHORTCUT_STEM}.lnk"))
        elif sys.platform != "darwin":
            entry = _install_application_entry()
            if entry is not None:
                created.append(entry)

    for path in created:
        logger.info("Created shortcut: %s", path)
    return created


def remove_desktop_shortcut() -> list[Path]:
    """Delete every shortcut this module creates; return the ones removed."""
    candidates: list[Path] = []
    target = shortcut_path()
    if target is not None:
        candidates.append(target)
    if sys.platform == "win32":
        programs = _start_menu_dir()
        if programs is not None:
            candidates.append(programs / f"{_SHORTCUT_STEM}.lnk")
    elif sys.platform != "darwin":
        data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        candidates.append(data / "applications" / f"{constants.APP_SLUG}.desktop")

    removed: list[Path] = []
    for path in candidates:
        try:
            if path.is_symlink() or path.exists():
                path.unlink()
                removed.append(path)
        except OSError:
            logger.warning("Could not remove %s", path, exc_info=True)
    return removed


def create_on_first_run(marker_dir: Path) -> Path | None:
    """Create the shortcut once, on the first launch after installation.

    PEP 517 wheels have no post-install hook, so ``pip install "wawekit[gui]"``
    cannot place an icon itself — the first launch does it instead. A marker
    file in ``marker_dir`` records that the attempt happened, so a user who
    deletes the shortcut does not find it back after the next launch, and a
    failure is not retried every time.

    Returns the desktop shortcut created, or ``None`` if nothing was done.
    Never raises: an icon is a convenience, and no failure here is worth
    blocking startup over.
    """
    marker = marker_dir / _MARKER_NAME
    if marker.exists():
        return None

    created: list[Path] = []
    try:
        existing = shortcut_path()
        if existing is not None and existing.exists():
            logger.debug("Desktop shortcut already present: %s", existing)
        else:
            created = create_desktop_shortcut()
    except ShortcutError as exc:
        logger.warning("Could not create the desktop shortcut: %s", exc)
    except Exception:  # noqa: BLE001 — startup must survive anything here
        logger.warning("Unexpected failure creating the desktop shortcut", exc_info=True)

    try:
        marker_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            f"{constants.APP_NAME} {constants.APP_VERSION} shortcut setup ran.\n"
            "Delete this file to have the app offer to create it again.\n",
            encoding="utf-8",
        )
    except OSError:
        logger.debug("Could not write the shortcut marker", exc_info=True)

    return created[0] if created else None


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``wawekit-shortcut`` console script."""
    import argparse

    parser = argparse.ArgumentParser(
        prog=f"{constants.APP_SLUG}-shortcut",
        description=f"Create or remove the {constants.APP_NAME} desktop shortcut.",
    )
    parser.add_argument(
        "--remove", action="store_true", help="delete the shortcut instead of creating it"
    )
    parser.add_argument(
        "--no-menu",
        action="store_true",
        help="only touch the desktop, leaving the Start/application menu alone",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        paths = (
            remove_desktop_shortcut()
            if args.remove
            else create_desktop_shortcut(start_menu=not args.no_menu)
        )
    except ShortcutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "Removed" if args.remove else "Created"
    if not paths:
        print("Nothing to do — no desktop or menu location was found.")
        return 0
    for path in paths:
        print(f"{verb}: {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover — module-as-script convenience
    raise SystemExit(main())
