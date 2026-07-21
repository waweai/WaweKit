"""Smoke tests — prove the walking skeleton stands up.

These are intentionally minimal: they assert that the core objects construct
without error. If any of these fail, the whole application is broken, so they
run fast and first.
"""

from __future__ import annotations

from wawekit import __version__
from wawekit.core.config import AppConfig, load_config


def test_version_is_a_string():
    assert isinstance(__version__, str)
    assert __version__.count(".") == 2  # semantic version x.y.z


def test_appconfig_defaults():
    cfg = AppConfig()
    assert cfg.theme in {"dark", "light"}
    assert cfg.window_width > 0
    assert cfg.window_height > 0


def test_appconfig_is_immutable():
    cfg = AppConfig()
    # frozen dataclass: assigning to a field must raise.
    import dataclasses

    try:
        cfg.theme = "light"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:  # pragma: no cover
        raise AssertionError("AppConfig should be immutable")


def test_load_config_returns_config(tmp_path):
    cfg = load_config(shipped_defaults=tmp_path / "missing.toml")
    assert isinstance(cfg, AppConfig)


def test_main_window_constructs(qtbot):
    """The main window builds with menus, toolbar and status bar."""
    from PySide6.QtWidgets import QApplication

    from wawekit.core.config import AppConfig
    from wawekit.gui.main_window import MainWindow
    from wawekit.gui.themes.theme_manager import ThemeManager

    theme_manager = ThemeManager(QApplication.instance(), "dark")
    window = MainWindow(AppConfig(), theme_manager)
    qtbot.addWidget(window)

    assert window.menuBar().actions()  # File/View/Help present
    assert window.statusBar() is not None
    assert theme_manager.current == "dark"
