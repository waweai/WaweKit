"""Tests for cross-toolkit standardizer comparison."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.services.reproducibility import analyze_divergence, compute_metrics
from wawekit.services.reproducibility.protocol import (
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
)
from wawekit.services.reproducibility.standardizers import (
    ChEMBLPipelineStandardizer,
    MolVSStandardizer,
    ProtocolStandardizer,
    Standardizer,
    available_standardizers,
    external_standardizers,
)

AVAILABLE = available_standardizers()
needs_chembl = pytest.mark.skipif(
    not AVAILABLE["ChEMBL pipeline"], reason="chembl_structure_pipeline not installed"
)
needs_molvs = pytest.mark.skipif(not AVAILABLE["MolVS"], reason="molvs not installed")


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_protocol_standardizer_satisfies_the_protocol():
    std = ProtocolStandardizer(PRESET_CHEMBL_LIKE)
    assert isinstance(std, Standardizer)
    assert std.name == "ChEMBL-like"
    assert std.is_ablatable is True


def test_protocol_standardizer_matches_the_direct_call():
    from wawekit.services.reproducibility.protocol import standardize

    mol = _mol("CC(=O)[O-].[Na+]")
    assert ProtocolStandardizer(PRESET_CHEMBL_LIKE).standardize_mol(mol) == standardize(
        mol, PRESET_CHEMBL_LIKE
    )


@needs_chembl
def test_chembl_pipeline_standardizer_runs_and_is_not_ablatable():
    std = ChEMBLPipelineStandardizer()
    assert isinstance(std, Standardizer)
    assert std.is_ablatable is False  # opaque: no operations to toggle
    form = std.standardize_mol(_mol("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]"))
    assert form.ok
    assert "Na" not in form.smiles  # the parent step strips the counter-ion


@needs_molvs
def test_molvs_configurations_differ_from_each_other():
    """The two MolVS configurations draw the salt-handling line differently."""
    mol = _mol("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]")
    default = MolVSStandardizer(super_parent=False).standardize_mol(mol)
    parent = MolVSStandardizer(super_parent=True).standardize_mol(mol)
    assert default.ok and parent.ok
    assert default.smiles != parent.smiles
    assert "Na" in default.smiles  # default keeps the counter-ion
    assert "Na" not in parent.smiles  # super_parent removes it


def test_external_standardizer_converts_failure_into_a_form_not_an_exception():
    """A third-party pipeline that raises must not abort a whole run."""
    from wawekit.services.reproducibility.standardizers import _ExternalStandardizer

    class Exploding(_ExternalStandardizer):
        name = "exploding"

        def _run(self, mol):
            raise ValueError("boom")

    form = Exploding().standardize_mol(_mol("CCO"))
    assert not form.ok
    assert form.error is not None and "boom" in form.error
    assert form.smiles == ""


def test_mixed_comparison_of_composed_and_external_standardizers():
    """A single audit may mix composed protocols with production pipelines."""
    standardizers: list[object] = [ProtocolStandardizer(PRESET_MINIMAL)]
    standardizers.extend(external_standardizers())
    if len(standardizers) < 2:
        pytest.skip("no external standardizers installed")

    records = [
        ("salt", _mol("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]")),
        ("clean", _mol("c1ccccc1")),
    ]
    run = analyze_divergence(records, tuple(standardizers), attribute_causes=True)
    metrics = compute_metrics(run)

    assert metrics.n_molecules == 2
    assert len(metrics.pairwise) == len(standardizers) * (len(standardizers) - 1) // 2
    # The salt is handled differently by at least one pair.
    assert metrics.n_labile >= 1


def test_attribution_is_skipped_rather_than_faked_without_an_ablatable_standardizer():
    """Opaque-only comparisons report divergence but must not invent causes.

    Cause attribution needs operations that can be switched off. With no
    ablatable standardizer present the honest output is an empty cause list —
    the point of this test is that the code reaches that state deliberately
    rather than crashing on a missing ``.operations`` attribute.
    """
    externals = external_standardizers()
    if len(externals) < 2:
        pytest.skip("needs two external standardizers")

    records = [("salt", _mol("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]"))]
    run = analyze_divergence(records, tuple(externals), attribute_causes=True)

    assert run.n_molecules == 1
    assert run.results[0].causes == ()  # cannot attribute, and does not pretend to


def test_attribution_still_works_when_one_ablatable_standardizer_is_present():
    externals = external_standardizers()
    if not externals:
        pytest.skip("needs an external standardizer")

    mixed = (ProtocolStandardizer(PRESET_AGGRESSIVE), *externals)
    records = [("salt", _mol("CC(=O)Oc1ccccc1C(=O)[O-].[Na+]"))]
    run = analyze_divergence(records, mixed, attribute_causes=True)

    assert run.results[0].is_labile
    assert run.results[0].causes  # the composed protocol supplies attribution


def test_available_standardizers_reports_booleans():
    report = available_standardizers()
    assert set(report) == {"ChEMBL pipeline", "MolVS"}
    assert all(isinstance(v, bool) for v in report.values())


def test_dialog_offers_external_standardizers_when_installed(qtbot):
    """The software paper claims users can select production pipelines.

    That claim is only true if the dialog actually surfaces them, so it is
    pinned here rather than left to inspection.
    """
    from wawekit.gui.dialogs.reproducibility_dialog import ReproducibilityDialog

    dialog = ReproducibilityDialog()
    qtbot.addWidget(dialog)

    offered = {std.name for _, std in dialog._external_boxes}
    if AVAILABLE["ChEMBL pipeline"]:
        assert "ChEMBL pipeline" in offered
    if AVAILABLE["MolVS"]:
        assert {"MolVS default", "MolVS super-parent"} <= offered


def test_dialog_selection_mixes_protocols_and_pipelines(qtbot):
    from wawekit.gui.dialogs.reproducibility_dialog import ReproducibilityDialog

    dialog = ReproducibilityDialog()
    qtbot.addWidget(dialog)
    for box, _ in dialog._external_boxes:
        box.setChecked(True)

    chosen, _ = dialog.result_options()
    assert len(chosen) >= 2
    assert any(s.is_ablatable for s in chosen)  # composed protocols still selected
    if dialog._external_boxes:
        assert any(not s.is_ablatable for s in chosen)  # and pipelines alongside them


def test_dialog_warns_when_attribution_is_impossible(qtbot):
    """Selecting only opaque pipelines must warn, not silently produce no causes."""
    from wawekit.gui.dialogs.reproducibility_dialog import ReproducibilityDialog

    dialog = ReproducibilityDialog()
    qtbot.addWidget(dialog)
    if len(dialog._external_boxes) < 2:
        pytest.skip("needs two external standardizers")

    for box, _ in dialog._protocol_boxes:
        box.setChecked(False)
    for box, _ in dialog._external_boxes:
        box.setChecked(True)

    assert "cannot be attributed" in dialog._hint.text()
