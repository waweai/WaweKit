"""Tests for the Settings dialog (offscreen Qt)."""

from __future__ import annotations

from wawekit.core.config import AppConfig
from wawekit.gui.dialogs.settings_dialog import SettingsDialog


def test_dialog_loads_the_current_config(qtbot):
    dialog = SettingsDialog(AppConfig(theme="light", log_level="DEBUG"))
    qtbot.addWidget(dialog)
    assert dialog._theme.currentData() == "light"
    assert dialog._log_level.currentText() == "DEBUG"


def test_edits_flow_into_a_new_config(qtbot):
    base = AppConfig(theme="dark", window_width=1234)
    dialog = SettingsDialog(base)
    qtbot.addWidget(dialog)

    dialog._theme.setCurrentIndex(dialog._theme.findData("light"))
    dialog._remember.setChecked(False)
    result = dialog.config(base)

    assert result.theme == "light"
    assert result.remember_window_geometry is False
    # Untouched fields are carried over from base, not reset.
    assert result.window_width == 1234


def test_restore_defaults_resets_controls(qtbot):
    dialog = SettingsDialog(AppConfig(theme="light", log_level="ERROR"))
    qtbot.addWidget(dialog)
    dialog._restore_defaults()
    defaults = AppConfig()
    assert dialog._theme.currentData() == defaults.theme
    assert dialog._log_level.currentText() == defaults.log_level
