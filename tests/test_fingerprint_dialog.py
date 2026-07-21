"""Tests for the fingerprint options dialog (headless, offscreen Qt).

Since Module 7 the controls live in ``FingerprintOptionsWidget`` and are covered
by ``test_fingerprint_options``. What remains the *dialog's* job — hosting the
widget and turning OK/Cancel into a return value — is what is tested here.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog

from wawekit.gui.dialogs.fingerprint_dialog import FingerprintDialog
from wawekit.models.fingerprints import FingerprintKind, FingerprintOptions


def test_dialog_reports_the_embedded_widgets_options(qtbot):
    dialog = FingerprintDialog()
    qtbot.addWidget(dialog)
    dialog._options.set_options(FingerprintOptions(kind=FingerprintKind.RDKIT, n_bits=1024))

    options = dialog.options()
    assert options.kind is FingerprintKind.RDKIT
    assert options.n_bits == 1024


def test_defaults_are_morgan_r2_2048(qtbot):
    dialog = FingerprintDialog()
    qtbot.addWidget(dialog)
    assert dialog.options() == FingerprintOptions()


def test_get_options_returns_none_when_cancelled(qtbot, monkeypatch):
    # exec() would block on a real event loop; stub it to simulate the user.
    monkeypatch.setattr(FingerprintDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert FingerprintDialog.get_options() is None


def test_get_options_returns_options_when_accepted(qtbot, monkeypatch):
    monkeypatch.setattr(FingerprintDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    assert FingerprintDialog.get_options() == FingerprintOptions()
