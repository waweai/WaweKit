"""Tests for the packaged theme stylesheets."""

from __future__ import annotations

import pytest

from wawekit.gui.themes.theme_manager import ThemeManager


def _stylesheet(qapp, theme: str) -> str:
    return ThemeManager(qapp, initial_theme=theme)._load_stylesheet(theme)


@pytest.mark.parametrize("theme", ThemeManager.available())
def test_stylesheet_loads(qapp, theme):
    assert _stylesheet(qapp, theme).strip()


@pytest.mark.parametrize("theme", ThemeManager.available())
def test_checked_radio_indicator_is_styled(qapp, theme):
    """Regression: a checked radio button rendered *no indicator at all*.

    Found in Module 7, the first module to use radio buttons. Qt's native style
    drew the checked dot invisibly against our backgrounds, so the similarity
    dialog gave the user no way to tell which query source was selected — while
    unchecked radios showed a circle, making it look like nothing was chosen.

    Only a screenshot catches the rendering itself; what this pins is that the
    explicit rule survives, since deleting it silently restores the bug.
    """
    qss = _stylesheet(qapp, theme)
    assert "QRadioButton::indicator:checked" in qss
    assert "qradialgradient" in qss
