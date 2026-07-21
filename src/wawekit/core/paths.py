r"""Cross-platform application directories.

Different operating systems put user config, data, and logs in different places:

* Windows : ``%APPDATA%\\Wawekit`` and ``%LOCALAPPDATA%\\Wawekit``
* macOS   : ``~/Library/Application Support/Wawekit``
* Linux   : ``~/.config/Wawekit`` and ``~/.local/share/Wawekit``

We *never* hardcode these. Instead we ask Qt's :class:`QStandardPaths`, which
already knows the correct location per platform. This keeps the app a good
citizen on every OS and avoids writing files next to the executable (which is
often read-only when installed).

All functions are pure and side-effect free *except* the ``ensure_*`` helpers,
which create the directory on first use.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths

from wawekit.core.constants import APP_NAME


def _base(location: QStandardPaths.StandardLocation) -> Path:
    """Return the OS-standard directory for ``location`` as a :class:`Path`.

    Qt returns an app-scoped path because we set the application name in
    :func:`wawekit.app.run` before any widget is created.
    """
    raw = QStandardPaths.writableLocation(location)
    if not raw:  # extremely rare; fall back to a home-relative directory
        raw = str(Path.home() / f".{APP_NAME.lower()}")
    return Path(raw)


def config_dir() -> Path:
    """User-writable directory for configuration files (settings.toml, etc.)."""
    return _base(QStandardPaths.StandardLocation.AppConfigLocation)


def data_dir() -> Path:
    """User-writable directory for application data (caches, exports, plugins)."""
    return _base(QStandardPaths.StandardLocation.AppDataLocation)


def log_dir() -> Path:
    """Directory for log files. Kept under the data dir for a single footprint."""
    return data_dir() / "logs"


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing and return it.

    Using ``exist_ok=True`` makes this safe to call repeatedly at startup.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_app_dirs() -> dict[str, Path]:
    """Create every standard app directory and return a name → path mapping.

    Called once during startup so the rest of the app can assume the
    directories exist.
    """
    dirs = {
        "config": config_dir(),
        "data": data_dir(),
        "logs": log_dir(),
    }
    for path in dirs.values():
        ensure_dir(path)
    return dirs
