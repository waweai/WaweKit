"""Load and apply Qt Style Sheets (the desktop equivalent of CSS).

Qt lets you restyle an entire application with a single stylesheet string
applied to the :class:`QApplication`. We keep those stylesheets in ``.qss``
files next to this module and load them with :mod:`importlib.resources`, which
works both from source *and* from a frozen PyInstaller bundle (unlike raw file
paths).

Since Module 3 the manager is a :class:`~PySide6.QtCore.QObject` that emits
:attr:`ThemeManager.theme_changed` — molecule depictions must re-render with a
different atom palette when the theme flips, so interested widgets subscribe
instead of the window pushing updates to each of them by hand (the observer
pattern, via Qt signals).
"""

from __future__ import annotations

import logging
from importlib import resources

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

#: Ordered mapping of theme key → (display name, stylesheet filename, is_dark).
#: Order determines the cycling order of ``toggle()``.
_THEMES: dict[str, tuple[str, str, bool]] = {
    "dark": ("Night", "dark.qss", True),
    "graphite": ("Graphite", "graphite.qss", True),
    "gray": ("Gray", "gray.qss", False),
    "moderate": ("Moderate", "moderate.qss", False),
    "light": ("Light", "light.qss", False),
    "creme_coffee": ("Creme Coffee", "creme_coffee.qss", False),
    "sahara": ("Sahara", "sahara.qss", False),
    "nebula": ("Nebula", "nebula.qss", True),
}

#: Fallback used if an unknown theme name is requested.
_DEFAULT_THEME = "dark"

#: Ordered list of keys for cycling.
_THEME_KEYS = list(_THEMES)


class ThemeManager(QObject):
    """Applies and toggles application-wide visual themes.

    Parameters
    ----------
    app:
        The running :class:`QApplication` whose stylesheet we control.
    initial_theme:
        Name of the theme to apply immediately (any key in ``_THEMES``).

    """

    #: Emitted with the new theme name after a theme has been applied.
    theme_changed = Signal(str)

    def __init__(self, app: QApplication, initial_theme: str = _DEFAULT_THEME) -> None:
        super().__init__()
        self._app = app
        self._current = ""
        self.apply(initial_theme)

    @property
    def current(self) -> str:
        """Name of the currently applied theme."""
        return self._current

    @property
    def is_dark(self) -> bool:
        """Whether the current theme is a dark variant (drives depiction palette)."""
        entry = _THEMES.get(self._current)
        if entry is not None:
            return entry[2]
        return self._current == "dark"

    @staticmethod
    def available() -> list[str]:
        """Return the list of selectable theme keys."""
        return list(_THEMES)

    @staticmethod
    def display_name(key: str) -> str:
        """Return the human-readable name for ``key``, or the key itself."""
        entry = _THEMES.get(key)
        return entry[0] if entry is not None else key.capitalize()

    @staticmethod
    def theme_is_dark(key: str) -> bool:
        """Return whether ``key`` is a dark-palette theme."""
        entry = _THEMES.get(key)
        return entry[2] if entry is not None else False

    def _load_stylesheet(self, theme: str) -> str:
        """Read the ``.qss`` text for ``theme`` from packaged resources."""
        filename = _THEMES[theme][1]
        resource = resources.files("wawekit.gui.themes").joinpath(filename)
        return resource.read_text(encoding="utf-8")

    def apply(self, theme: str) -> None:
        """Apply ``theme`` to the whole application and notify subscribers.

        Unknown names fall back to the default theme rather than raising, so a
        stale config value can never prevent startup.
        """
        if theme not in _THEMES:
            logger.warning("Unknown theme %r; falling back to %r", theme, _DEFAULT_THEME)
            theme = _DEFAULT_THEME
        try:
            self._app.setStyleSheet(self._load_stylesheet(theme))
        except (OSError, ModuleNotFoundError) as exc:
            logger.error("Failed to load theme %r: %s", theme, exc)
            return

        from PySide6.QtGui import QColor, QPalette

        palette = self._app.palette()
        entry = _THEMES.get(theme)
        is_dark = entry[2] if entry is not None else False
        link_color = QColor("#6ab0e0" if is_dark else "#0055aa")
        palette.setColor(QPalette.ColorGroup.All, QPalette.ColorRole.Link, link_color)
        self._app.setPalette(palette)

        self._current = theme
        logger.info("Applied %s theme", theme)
        self.theme_changed.emit(theme)

    def toggle(self) -> str:
        """Cycle to the next theme and return the new theme's key."""
        try:
            idx = _THEME_KEYS.index(self._current)
        except ValueError:
            idx = -1
        nxt = _THEME_KEYS[(idx + 1) % len(_THEME_KEYS)]
        self.apply(nxt)
        return self._current
