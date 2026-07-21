"""Tests for plugin discovery, loading, and failure isolation (no Qt)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from wawekit.plugins.base import PluginContext
from wawekit.plugins.manager import discover_plugins, load_plugins


@dataclass
class _FakeEntryPoint:
    name: str
    _target: type | Exception

    def load(self):
        if isinstance(self._target, Exception):
            raise self._target
        return self._target


class _GoodPlugin:
    name = "Good Plugin"
    version = "1.0"

    def activate(self, context: PluginContext) -> None:
        context.add_menu_action("Do Something", lambda: None)


class _BrokenActivatePlugin:
    name = "Broken Plugin"
    version = "1.0"

    def activate(self, context: PluginContext) -> None:
        raise RuntimeError("plugin exploded on activate")


class _NotAPlugin:
    """Missing the required attributes — should be rejected, not crash."""


def _context() -> PluginContext:
    return PluginContext(add_menu_action=MagicMock(), add_dock=MagicMock())


def test_discover_plugins_resolves_registered_entry_points():
    fake_eps = [_FakeEntryPoint("good", _GoodPlugin)]
    with patch("wawekit.plugins.manager.entry_points", return_value=fake_eps):
        found = discover_plugins()
    assert found == [("good", _GoodPlugin)]


def test_discover_plugins_skips_unresolvable_entry_points():
    fake_eps = [
        _FakeEntryPoint("broken_import", ImportError("no such module")),
        _FakeEntryPoint("good", _GoodPlugin),
    ]
    with patch("wawekit.plugins.manager.entry_points", return_value=fake_eps):
        found = discover_plugins()
    assert found == [("good", _GoodPlugin)]  # the broken one is skipped, not raised


def test_load_plugins_activates_a_good_plugin():
    fake_eps = [_FakeEntryPoint("good", _GoodPlugin)]
    context = _context()
    with patch("wawekit.plugins.manager.entry_points", return_value=fake_eps):
        report = load_plugins(context)

    assert len(report.loaded) == 1
    assert report.loaded[0].name == "Good Plugin"
    context._add_menu_action.assert_called_once()  # activate() ran
    assert report.failures == []


def test_load_plugins_isolates_a_plugin_that_fails_to_activate():
    fake_eps = [
        _FakeEntryPoint("good", _GoodPlugin),
        _FakeEntryPoint("broken", _BrokenActivatePlugin),
    ]
    with patch("wawekit.plugins.manager.entry_points", return_value=fake_eps):
        report = load_plugins(_context())

    # The good plugin still loaded despite the broken one failing.
    assert len(report.loaded) == 1
    assert report.loaded[0].name == "Good Plugin"
    assert len(report.failures) == 1
    assert report.failures[0].entry_point_name == "broken"
    assert "exploded" in report.failures[0].error


def test_load_plugins_rejects_an_object_missing_the_protocol_shape():
    fake_eps = [_FakeEntryPoint("not_a_plugin", _NotAPlugin)]
    with patch("wawekit.plugins.manager.entry_points", return_value=fake_eps):
        report = load_plugins(_context())

    assert report.loaded == []
    assert len(report.failures) == 1


def test_load_plugins_with_no_entry_points_returns_empty_report():
    with patch("wawekit.plugins.manager.entry_points", return_value=[]):
        report = load_plugins(_context())
    assert report.loaded == []
    assert report.failures == []
