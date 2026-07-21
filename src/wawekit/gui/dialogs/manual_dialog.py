"""The in-app user manual (Help → User Manual, F1).

The manual ships as packaged HTML + screenshots under ``resources/manual`` and
renders in a :class:`~PySide6.QtWidgets.QTextBrowser` — no browser, no internet,
works identically from source and from a frozen bundle. It is shown *non-modal*
so a user can follow the steps in the app while reading them.
"""

from __future__ import annotations

import logging
from importlib import resources

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


def _load_manual() -> tuple[str, str, str]:
    """Return the manual's HTML, its image directory, and the icons directory.

    Returns ``("", "", "")`` when the packaged asset is missing — the dialog then
    shows a short apology instead of crashing; documentation must never take
    the application down.
    """
    try:
        base = resources.files("wawekit.resources").joinpath("manual")
        icons = resources.files("wawekit.resources").joinpath("icons")
        return (
            base.joinpath("manual.html").read_text(encoding="utf-8"),
            str(base),
            str(icons),
        )
    except (OSError, ModuleNotFoundError):
        logger.warning("Manual asset not found")
        return "", "", ""


class ManualDialog(QDialog):
    """A scrollable, linked, illustrated user manual.

    Parameters
    ----------
    parent:
        Standard Qt parent.

    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WaweKit User Manual")
        self.resize(1000, 760)

        self._browser = QTextBrowser(self)
        self._browser.setOpenExternalLinks(False)  # in-page anchors only; no surprise browser
        self._html, self._image_dir, self._icons_dir = _load_manual()

        self._update_browser_style()

        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._browser)
        layout.addWidget(self._buttons)

        # Connect to theme changes to dynamically re-style links
        if parent and hasattr(parent, "_theme_manager"):
            parent._theme_manager.theme_changed.connect(self._on_theme_changed)

    def _update_browser_style(self) -> None:
        """Apply a high-contrast paper style layout for consistent readability."""
        # Set text browser colors to a clean white page with dark text
        self._browser.setStyleSheet("background-color: #ffffff; color: #1e1f22;")

        # Style standard inline HTML elements
        self._browser.document().setDefaultStyleSheet(
            "body { background-color: #ffffff; color: #1e1f22; font-family: sans-serif; }\n"
            "a { color: #0055aa; text-decoration: none; font-weight: bold; }\n"
            "code { background-color: #f4f5f7; color: #1e1f22; "
            "padding: 2px 4px; border-radius: 3px; }"
        )

        if self._html:
            # Set search paths to look in both the manual folder and the icons folder
            self._browser.setSearchPaths([self._image_dir, self._icons_dir])
            # Dynamically replace the low-resolution logo.png with the high-resolution brand logo
            html_high_res = self._html.replace('src="logo.png"', 'src="wawekit_logo.png"')
            self._browser.setHtml(html_high_res)
        else:
            self._browser.setHtml(
                "<h2>Manual not available</h2>"
                "<p>The packaged manual could not be found. Please see the "
                "online documentation instead (Help → About for the project link).</p>"
            )

    def _on_theme_changed(self) -> None:
        """Handle theme change signal from the parent window."""
        self._update_browser_style()
