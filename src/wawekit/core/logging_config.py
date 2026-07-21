"""Centralized logging setup.

Professional applications *never* use ``print`` for diagnostics. Instead they
configure the standard :mod:`logging` module once at startup, then every module
does ``logger = logging.getLogger(__name__)`` and simply logs. Benefits:

* Messages carry a level (DEBUG/INFO/WARNING/ERROR) and can be filtered.
* Output goes to both the console *and* a rotating file for bug reports.
* No module needs to know *where* logs go — that policy lives here.

The file handler rotates so logs never grow without bound.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from wawekit.core.paths import ensure_dir, log_dir

#: Format shared by all handlers. Includes time, level, logger name, message.
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

#: Rotate the log file at ~1 MB, keeping a few historical files.
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3


def setup_logging(level: str = "INFO") -> Path:
    """Configure the root logger with console + rotating file handlers.

    Idempotent: calling it twice will not duplicate handlers, which matters for
    tests that construct the app repeatedly.

    Parameters
    ----------
    level:
        Logging level name (``"DEBUG"``, ``"INFO"``, ...). Invalid names fall
        back to ``INFO`` instead of raising.

    Returns
    -------
    Path
        The full path to the active log file (useful for a "show logs" action).

    """
    numeric_level = logging.getLevelName(level.upper())
    if not isinstance(numeric_level, int):
        numeric_level = logging.INFO

    root = logging.getLogger()
    root.setLevel(numeric_level)

    # Remove handlers we previously installed so repeated calls stay clean.
    for handler in list(root.handlers):
        if getattr(handler, "_wawekit_managed", False):
            root.removeHandler(handler)

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console._wawekit_managed = True  # type: ignore[attr-defined]
    root.addHandler(console)

    logfile = ensure_dir(log_dir()) / "wawekit.log"
    file_handler = RotatingFileHandler(
        logfile, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler._wawekit_managed = True  # type: ignore[attr-defined]
    root.addHandler(file_handler)

    logging.getLogger(__name__).debug("Logging initialized at level %s", level)
    return logfile
