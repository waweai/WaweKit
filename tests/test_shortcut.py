"""Tests for desktop-shortcut creation (pure stdlib, no Qt).

Every test redirects the desktop/menu locations into ``tmp_path`` — a test
suite must never write to the developer's real desktop.
"""

from __future__ import annotations

import sys

import pytest

from wawekit.core import constants, shortcut


@pytest.fixture
def fake_desktop(tmp_path, monkeypatch):
    """Point every OS location this module writes to at a temp directory."""
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    menu = tmp_path / "Menu"
    menu.mkdir()
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: desktop)
    monkeypatch.setattr(
        shortcut, "_start_menu_dir", lambda: menu if sys.platform == "win32" else None
    )
    monkeypatch.setattr(shortcut, "_install_application_entry", lambda: menu / "entry.desktop")
    monkeypatch.setattr(shortcut, "state_dir", lambda: tmp_path / "state")
    return desktop


def test_launcher_command_is_runnable():
    program, *args = shortcut.launcher_command()
    assert program
    # Either a frozen/console executable on its own, or `python -m wawekit`.
    assert args in ([], ["-m", constants.APP_SLUG])


def test_shortcut_path_uses_the_platform_extension(fake_desktop):
    path = shortcut.shortcut_path()
    assert path is not None
    assert path.parent == fake_desktop
    expected = {"win32": ".lnk", "darwin": ".command"}.get(sys.platform, ".desktop")
    assert path.suffix == expected


def test_no_desktop_directory_is_not_an_error(monkeypatch):
    monkeypatch.setattr(shortcut, "desktop_dir", lambda: None)
    monkeypatch.setattr(shortcut, "_start_menu_dir", lambda: None)
    monkeypatch.setattr(shortcut, "_install_application_entry", lambda: None)
    assert shortcut.shortcut_path() is None
    assert shortcut.create_desktop_shortcut() == []


@pytest.mark.skipif(sys.platform == "win32", reason="Windows uses a .lnk, not a .desktop file")
@pytest.mark.skipif(sys.platform == "darwin", reason="macOS uses a .command launcher")
def test_linux_desktop_entry_is_valid_and_executable(fake_desktop):
    created = shortcut.create_desktop_shortcut(start_menu=False)
    entry = created[0]
    text = entry.read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]")
    assert f"Name={constants.APP_NAME}" in text
    assert "Exec=" in text and "Terminal=false" in text
    assert entry.stat().st_mode & 0o111  # a .desktop file must be executable


@pytest.mark.skipif(sys.platform != "win32", reason="Windows .lnk creation")
def test_windows_creates_a_real_lnk(fake_desktop):
    created = shortcut.create_desktop_shortcut(start_menu=False)
    assert len(created) == 1
    lnk = created[0]
    assert lnk.is_file()
    # A .lnk always starts with the 20-byte shell-link header magic.
    assert lnk.read_bytes()[:4] == b"\x4c\x00\x00\x00"


def test_create_is_idempotent(fake_desktop):
    first = shortcut.create_desktop_shortcut(start_menu=False)
    second = shortcut.create_desktop_shortcut(start_menu=False)
    assert first == second
    assert all(path.exists() or path.is_symlink() for path in second)


def test_remove_deletes_what_create_made(fake_desktop):
    created = shortcut.create_desktop_shortcut(start_menu=False)
    removed = shortcut.remove_desktop_shortcut()
    assert created[0] in removed
    assert not created[0].exists()
    # Removing again is a no-op rather than an error.
    assert shortcut.remove_desktop_shortcut() == []


def test_first_run_creates_once_then_never_again(tmp_path, monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(shortcut, "shortcut_path", lambda: tmp_path / "Wawekit.lnk")
    monkeypatch.setattr(
        shortcut, "create_desktop_shortcut", lambda *a, **k: calls.append(1) or [tmp_path / "x"]
    )
    marker_dir = tmp_path / "config"

    assert shortcut.create_on_first_run(marker_dir) is not None
    assert (marker_dir / shortcut._MARKER_NAME).is_file()

    # A user who deletes the icon must not have it reappear on the next launch.
    assert shortcut.create_on_first_run(marker_dir) is None
    assert len(calls) == 1


def test_first_run_survives_a_failure_and_does_not_retry(tmp_path, monkeypatch):
    calls: list[int] = []

    def boom(*_args, **_kwargs):
        calls.append(1)
        raise shortcut.ShortcutError("no shell available")

    monkeypatch.setattr(shortcut, "shortcut_path", lambda: tmp_path / "Wawekit.lnk")
    monkeypatch.setattr(shortcut, "create_desktop_shortcut", boom)
    marker_dir = tmp_path / "config"

    assert shortcut.create_on_first_run(marker_dir) is None  # swallowed, no raise
    assert (marker_dir / shortcut._MARKER_NAME).is_file()
    assert shortcut.create_on_first_run(marker_dir) is None
    assert len(calls) == 1


def test_first_run_skips_when_a_shortcut_already_exists(tmp_path, monkeypatch):
    """The Windows installer places its own icon; first run must not duplicate it."""
    existing = tmp_path / "Wawekit.lnk"
    existing.write_bytes(b"stub")
    calls: list[int] = []
    monkeypatch.setattr(shortcut, "shortcut_path", lambda: existing)
    monkeypatch.setattr(shortcut, "create_desktop_shortcut", lambda *a, **k: calls.append(1) or [])

    assert shortcut.create_on_first_run(tmp_path / "config") is None
    assert calls == []


def test_cli_creates_and_removes(fake_desktop, capsys):
    assert shortcut.main(["--no-menu"]) == 0
    assert "Created:" in capsys.readouterr().out
    assert shortcut.main(["--remove"]) == 0
    assert "Removed:" in capsys.readouterr().out
