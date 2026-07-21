"""Application composition root.

This is the *one* module that assembles the whole application in the correct
order and owns the Qt event loop. Everything else is a component that gets wired
together here. Keeping assembly in a single place (the "composition root"
pattern) makes startup easy to read and reason about.

Startup sequence
----------------
1. Create the QApplication and set identity (name/org) — this makes Qt's
   standard-path lookups return app-scoped directories.
2. Ensure the user data/log/config directories exist.
3. Load configuration (defaults + user overrides).
4. Initialize logging at the configured level.
5. Apply the theme.
6. Build and show the main window.
7. Run the event loop.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

try:
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover — depends on how the user installed
    # Qt lives in the optional [gui] extra so that `pip install wawekit` stays a
    # lightweight headless library (see pyproject). Someone who installed it
    # that way and then ran `wawekit` deserves a one-line instruction rather
    # than an import traceback pointing into PySide6.
    raise SystemExit(
        "The WaweKit desktop application requires the optional GUI dependencies.\n"
        "Install them with:\n\n"
        "    pip install 'wawekit[gui]'\n\n"
        "The analysis library and the reproducibility auditor work without them, e.g.\n"
        "    python -m wawekit.services.reproducibility.benchmark molecules.smi"
    ) from exc

from wawekit.core import constants
from wawekit.core.config import load_config
from wawekit.core.logging_config import setup_logging
from wawekit.core.paths import ensure_app_dirs

logger = logging.getLogger(__name__)

#: Location of the shipped default settings, relative to the repo root.
#: When frozen by PyInstaller this file may be absent, which is fine — the
#: dataclass defaults still apply.
_SHIPPED_DEFAULTS = Path(__file__).resolve().parents[2] / "config" / "default_settings.toml"

#: How long the branding splash stays up in total (window build time included).
_SPLASH_MS = 2500


def _claim_windows_taskbar_identity() -> None:
    """Make the Windows taskbar show *our* icon, not the Python interpreter's.

    When the app runs via ``python.exe``, Windows groups its windows under the
    host executable and shows python.exe's icon in the taskbar, ignoring the
    window icon. Registering an explicit AppUserModelID tells Windows this
    process is its own application, so the taskbar uses the window icon (the
    WaweKit badge). A no-op on other platforms and harmless if it fails.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            f"{constants.ORG_NAME}.{constants.APP_NAME}"
        )
    except (OSError, AttributeError):  # pragma: no cover — very old Windows only
        logger.debug("Could not set AppUserModelID", exc_info=True)


def _create_application(argv: list[str]) -> QApplication:
    """Create the QApplication and set its identity for path scoping."""
    _claim_windows_taskbar_identity()
    app = QApplication(argv)
    app.setApplicationName(constants.APP_NAME)
    app.setApplicationDisplayName(constants.APP_NAME)
    app.setOrganizationName(constants.ORG_NAME)
    app.setApplicationVersion(constants.APP_VERSION)
    return app


def run(argv: list[str] | None = None) -> int:
    """Start the application and block until it exits.

    Parameters
    ----------
    argv:
        Command-line arguments; defaults to :data:`sys.argv`.

    Returns
    -------
    int
        The Qt event loop's exit code (0 on clean exit).

    """
    argv = list(sys.argv if argv is None else argv)

    app = _create_application(argv)
    ensure_app_dirs()

    config = load_config(shipped_defaults=_SHIPPED_DEFAULTS)
    logfile = setup_logging(config.log_level)
    logger.info("Starting %s %s", constants.APP_NAME, constants.APP_VERSION)
    logger.info("Log file: %s", logfile)

    # Imported here (not at module top) so logging/config are ready first and so
    # importing wawekit.app never forces the GUI stack to load prematurely.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QSplashScreen

    from wawekit.gui.icons import get_app_icon, get_brand_pixmap
    from wawekit.gui.main_window import MainWindow
    from wawekit.gui.themes.theme_manager import ThemeManager

    app.setWindowIcon(get_app_icon())

    # Branding splash: show the WaweKit logo while the main window is built,
    # holding it for a short beat so the brand registers before the app appears.
    # If the asset is missing the app simply starts directly — never crash on
    # branding.
    splash: QSplashScreen | None = None
    splash_shown_at = time.monotonic()
    logo = get_brand_pixmap("wawekit_logo", width=420)
    if not logo.isNull():
        splash = QSplashScreen(logo)
        splash.show()
        app.processEvents()  # paint the splash before the (heavier) window build

    theme_manager = ThemeManager(app, initial_theme=config.theme)
    window = MainWindow(config=config, theme_manager=theme_manager)

    if splash is not None:

        def _reveal() -> None:
            splash.finish(window)
            window.show()

        # Hold the splash for what remains of the branding beat (window
        # construction already consumed part of it), then reveal the app.
        elapsed_ms = int((time.monotonic() - splash_shown_at) * 1000)
        QTimer.singleShot(max(0, _SPLASH_MS - elapsed_ms), _reveal)
    else:
        window.show()

    exit_code = app.exec()
    logger.info("Application exited with code %s", exit_code)
    return exit_code
