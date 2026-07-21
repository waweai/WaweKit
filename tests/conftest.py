"""Shared pytest fixtures.

Qt requires exactly one :class:`QApplication` per process. ``pytest-qt`` provides
a ``qtbot``/``qapp`` fixture that manages this for us, so GUI code can be
constructed and driven inside tests without a real display (using the ``offscreen``
Qt platform in CI).
"""

from __future__ import annotations

import os
import sys

import pytest

# Force Qt to use a headless platform plugin during tests so they run on CI and
# on machines without a display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture()
def app_config():
    """Return a default AppConfig for tests that need one."""
    from wawekit.core.config import AppConfig

    return AppConfig()


def pytest_unconfigure(config: pytest.Config) -> None:
    """Skip Python's normal interpreter teardown after the test session ends.

    QtWebEngine (used by the 3D conformer viewer, Module 9) has a known
    Chromium-shutdown bug that segfaults during native library finalization —
    *after* every test has already run and pytest has recorded pass/fail. The
    crash is in teardown, not in any test, so re-running the exact same
    interpreter shutdown sequence gains nothing. Exiting immediately with the
    real exit status pytest already computed sidesteps the crash without
    masking an actual test failure.

    ``pytest_unconfigure`` (not ``pytest_sessionfinish``) is the deliberate
    choice here: the terminal reporter prints its "FAILURES" / "N passed"
    summary from a *hookwrapper* around ``pytest_sessionfinish``, and a
    hookwrapper's post-yield code runs only after every plain hookimpl
    (ours included) has already returned — so hooking ``pytest_sessionfinish``
    directly, even with ``trylast=True``, silently ate the entire summary on
    any run with output worth seeing. ``pytest_unconfigure`` fires strictly
    after ``pytest_sessionfinish`` (and everything it wraps) has finished, so
    the summary is intact by the time this exits the process.
    """
    exitstatus = getattr(config, "_wawekit_exitstatus", 0)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exitstatus)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Stash the real exit status where ``pytest_unconfigure`` can read it.

    ``pytest_unconfigure`` doesn't receive ``exitstatus`` directly (it's a
    config-level hook, not a session-level one), so it's captured here first.
    """
    session.config._wawekit_exitstatus = int(exitstatus)
