"""Tests for configuration loading and saving (pure stdlib, no Qt)."""

from __future__ import annotations

from wawekit.core.config import AppConfig, _read_toml, load_config, save_config


def test_save_writes_a_readable_toml_file(tmp_path):
    path = tmp_path / "settings.toml"
    config = AppConfig(theme="light", log_level="DEBUG", remember_window_geometry=False)
    written = save_config(config, path)

    assert written == path
    assert path.exists()
    raw = _read_toml(path)
    assert raw["theme"] == "light"
    assert raw["log_level"] == "DEBUG"
    assert raw["remember_window_geometry"] is False  # bool, not 0/1
    assert raw["window_width"] == config.window_width


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "settings.toml"
    original = AppConfig(theme="light", log_level="WARNING", window_width=1000, window_height=700)
    save_config(original, path)

    # load_config reads <config_dir>/settings.toml; here we read the file directly
    # to keep the test independent of the OS config directory.
    loaded = AppConfig(**_read_toml(path))
    assert loaded == original


def test_bool_serializes_as_true_false_not_int(tmp_path):
    path = tmp_path / "s.toml"
    save_config(AppConfig(remember_window_geometry=True), path)
    text = path.read_text(encoding="utf-8")
    assert "remember_window_geometry = true" in text
    # A bool must never come out as an int like `remember_window_geometry = 1`.
    assert "remember_window_geometry = 1" not in text


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "settings.toml"
    path.write_text('theme = "light"\nstray_key = 42\n', encoding="utf-8")
    config = load_config(shipped_defaults=path)
    assert config.theme == "light"  # known key applied, stray ignored, no crash


def test_defaults_when_no_file():
    config = load_config()
    assert isinstance(config, AppConfig)
    assert config.theme in {"dark", "light"}
