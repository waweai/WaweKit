"""The Settings (Preferences) dialog.

Edits an :class:`~wawekit.core.config.AppConfig`. The dialog is a pure editor: it
reads a config in, returns a new one out, and knows nothing about *applying* or
*saving* — the window does that, so the dialog stays testable and reusable.

Only the genuinely user-facing settings are exposed: the theme, the log level and
whether to remember the window layout. ``window_width`` / ``window_height`` are
the *fallback* size used when no saved geometry exists, so they are managed by the
window itself rather than surfaced as a control.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from wawekit.core.config import AppConfig

#: Log levels offered, coarse-to-fine.
_LOG_LEVELS = ("ERROR", "WARNING", "INFO", "DEBUG")

#: Selectable themes (kept in step with ThemeManager, but the dialog does not
#: import it — it only edits the string the window later applies).
_THEMES = ("dark", "graphite", "gray", "moderate", "light", "creme_coffee", "sahara", "nebula")

#: Human-readable labels for each theme key, in the same order.
_THEME_LABELS = {
    "dark": "Night",
    "graphite": "Graphite",
    "gray": "Gray",
    "moderate": "Moderate",
    "light": "Light",
    "creme_coffee": "Creme Coffee",
    "sahara": "Sahara",
    "nebula": "Nebula",
}


class SettingsDialog(QDialog):
    """Edit the application's persistent settings.

    Parameters
    ----------
    config:
        The current configuration to load into the controls.

    """

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)

        self._theme = QComboBox(self)
        for theme in _THEMES:
            self._theme.addItem(_THEME_LABELS.get(theme, theme.capitalize()), theme)
        self._theme.setCurrentIndex(max(0, self._theme.findData(config.theme)))

        self._log_level = QComboBox(self)
        self._log_level.addItems(_LOG_LEVELS)
        self._log_level.setCurrentText(
            config.log_level if config.log_level in _LOG_LEVELS else "INFO"
        )
        self._log_level.setToolTip("How much detail is written to the log file.")

        self._remember = QCheckBox("Remember window size, position and panel layout", self)
        self._remember.setChecked(config.remember_window_geometry)

        form = QFormLayout()
        form.addRow("Theme:", self._theme)
        form.addRow("Log level:", self._log_level)
        form.addRow(self._remember)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _restore_defaults(self) -> None:
        """Reset every control to the AppConfig field defaults."""
        defaults = AppConfig()
        self._theme.setCurrentIndex(max(0, self._theme.findData(defaults.theme)))
        self._log_level.setCurrentText(defaults.log_level)
        self._remember.setChecked(defaults.remember_window_geometry)

    def config(self, base: AppConfig) -> AppConfig:
        """Return ``base`` with the dialog's edits applied.

        Only the exposed fields change; ``base`` supplies the rest (the fallback
        window size), so nothing is silently reset.
        """
        return base.with_overrides(
            theme=self._theme.currentData(),
            log_level=self._log_level.currentText(),
            remember_window_geometry=self._remember.isChecked(),
        )

    @staticmethod
    def edit(config: AppConfig, parent: QWidget | None = None) -> AppConfig | None:
        """Show the dialog modally; return the edited config, or ``None`` if cancelled."""
        dialog = SettingsDialog(config, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.config(config)
        return None
