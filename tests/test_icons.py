"""Tests for the packaged icon loader (offscreen Qt)."""

from __future__ import annotations

from wawekit.gui.icons import get_icon


def test_known_icons_load(qtbot):
    for name in ("app", "open", "theme", "standardize"):
        icon = get_icon(name)
        assert not icon.isNull(), f"icon {name!r} failed to load"


def test_missing_icon_returns_empty_not_crash(qtbot):
    icon = get_icon("does-not-exist")
    assert icon.isNull()
