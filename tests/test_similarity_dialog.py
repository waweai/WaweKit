"""Tests for the similarity search dialog (headless, offscreen Qt)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox

from wawekit.gui.dialogs.similarity_dialog import SimilarityDialog
from wawekit.models.fingerprints import FingerprintKind, FingerprintOptions
from wawekit.models.similarity import SimilarityMetric
from wawekit.services.io.molecule_loader import parse_smiles

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
PARACETAMOL = "CC(=O)Nc1ccc(O)cc1"


def _record(smiles: str, name: str):
    record = parse_smiles(smiles, name=name)
    assert record is not None, f"test data invalid: {smiles}"
    return record


def _ok(dialog: SimilarityDialog):
    return dialog._buttons.button(QDialogButtonBox.StandardButton.Ok)


# ------------------------------------------------------------- query source
def test_selection_is_the_default_query_when_one_exists(qtbot):
    selected = _record(ASPIRIN, "aspirin")
    dialog = SimilarityDialog(selected)
    qtbot.addWidget(dialog)

    assert dialog._use_selection.isChecked()
    assert dialog.request().query_name == "aspirin"
    assert _ok(dialog).isEnabled()


def test_without_a_selection_the_dialog_falls_back_to_pasting(qtbot):
    dialog = SimilarityDialog(None)
    qtbot.addWidget(dialog)

    assert not dialog._use_selection.isEnabled()
    assert dialog._use_paste.isChecked()
    # Nothing pasted yet, so there is no query and OK must not be available.
    assert not _ok(dialog).isEnabled()
    assert dialog.request() is None


def test_pasted_smiles_becomes_the_query(qtbot):
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"))
    qtbot.addWidget(dialog)

    dialog._use_paste.setChecked(True)
    dialog._smiles_edit.setText(PARACETAMOL)

    request = dialog.request()
    assert request.query_name == "Pasted query"
    assert _ok(dialog).isEnabled()


def test_switching_back_to_the_selection_ignores_the_pasted_text(qtbot):
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"))
    qtbot.addWidget(dialog)

    dialog._use_paste.setChecked(True)
    dialog._smiles_edit.setText(PARACETAMOL)
    dialog._use_selection.setChecked(True)

    assert dialog.request().query_name == "aspirin"


# ---------------------------------------------------------- live validation
def test_invalid_smiles_disables_ok_and_says_so(qtbot):
    dialog = SimilarityDialog(None)
    qtbot.addWidget(dialog)

    dialog._smiles_edit.setText("C1CC")  # unclosed ring
    assert not _ok(dialog).isEnabled()
    assert "not a valid" in dialog._query_status.text().lower()
    assert dialog.request() is None


def test_valid_smiles_reports_the_parsed_molecule(qtbot):
    dialog = SimilarityDialog(None)
    qtbot.addWidget(dialog)

    dialog._smiles_edit.setText(ASPIRIN)
    assert _ok(dialog).isEnabled()
    assert "C9H8O4" in dialog._query_status.text()


def test_validation_recovers_when_the_text_is_corrected(qtbot):
    dialog = SimilarityDialog(None)
    qtbot.addWidget(dialog)

    dialog._smiles_edit.setText("C1CC")
    assert not _ok(dialog).isEnabled()
    dialog._smiles_edit.setText("C1CC1")
    assert _ok(dialog).isEnabled()


def test_empty_paste_prompts_rather_than_warns(qtbot):
    dialog = SimilarityDialog(None)
    qtbot.addWidget(dialog)

    dialog._smiles_edit.setText("")
    # An empty box is not an error — the user simply hasn't typed yet.
    assert "⚠" not in dialog._query_status.text()
    assert not _ok(dialog).isEnabled()


# ------------------------------------------------------------------ options
def test_default_metric_is_tanimoto(qtbot):
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"))
    qtbot.addWidget(dialog)
    assert dialog.request().metric is SimilarityMetric.TANIMOTO


def test_selected_metric_is_a_real_enum_member_not_a_string(qtbot):
    # Same QVariant round-trip trap as FingerprintKind in Module 6.
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"))
    qtbot.addWidget(dialog)
    for metric in SimilarityMetric:
        dialog._metric.setCurrentIndex(dialog._metric.findData(metric))
        selected = dialog.request().metric
        assert type(selected) is SimilarityMetric
        assert selected is metric


def test_dialog_opens_on_the_supplied_encoding(qtbot):
    # So a second search doesn't silently re-encode the dataset a new way.
    wanted = FingerprintOptions(kind=FingerprintKind.MACCS)
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"), wanted)
    qtbot.addWidget(dialog)
    assert dialog.request().fingerprint.kind is FingerprintKind.MACCS


def test_encoding_reaches_the_request(qtbot):
    dialog = SimilarityDialog(_record(ASPIRIN, "aspirin"))
    qtbot.addWidget(dialog)
    dialog._fingerprint.set_options(FingerprintOptions(radius=3, n_bits=1024))
    assert dialog.request().fingerprint == FingerprintOptions(radius=3, n_bits=1024)


# ------------------------------------------------------------ static factory
def test_get_request_returns_none_when_cancelled(qtbot, monkeypatch):
    monkeypatch.setattr(SimilarityDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert SimilarityDialog.get_request(_record(ASPIRIN, "aspirin")) is None


def test_get_request_returns_the_request_when_accepted(qtbot, monkeypatch):
    monkeypatch.setattr(SimilarityDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    request = SimilarityDialog.get_request(_record(ASPIRIN, "aspirin"))
    assert request is not None
    assert request.query_name == "aspirin"
