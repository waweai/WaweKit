"""Tests for structural alerts calculation using RDKit's FilterCatalog."""

from __future__ import annotations

from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.alerts import compute_alerts, compute_alerts_for_records


def test_clean_molecule_no_alerts():
    """Verify that a clean molecule like ethanol has no alerts."""
    mol = Chem.MolFromSmiles("CCO")
    record = MoleculeRecord(mol=mol, name="Ethanol")
    # Lazy property triggers computation
    assert len(record.alerts) == 0


def test_quinone_pains_alert():
    """Verify that 1,4-benzoquinone triggers a PAINS/Brenk alert."""
    mol = Chem.MolFromSmiles("O=C1C=CC(=O)C=C1")
    record = MoleculeRecord(mol=mol, name="Quinone")
    alerts = record.alerts
    assert len(alerts) > 0
    # Should flag a quinone/quinone-like alert
    assert any("quinone" in a.lower() or "brenk" in a.lower() for a in alerts)


def test_catechol_brenk_alert():
    """Verify that catechol triggers an alert."""
    # Hydroxyl oxygen is never aromatic; the correct SMILES uses uppercase O.
    mol = Chem.MolFromSmiles("Oc1ccccc1O")
    record = MoleculeRecord(mol=mol, name="Catechol")
    alerts = record.alerts
    assert len(alerts) > 0
    assert any("catechol" in a.lower() or "brenk" in a.lower() for a in alerts)


def test_compute_alerts_on_none_mol_returns_empty_not_an_error():
    """A None molecule is 'nothing to check', not a failure worth reporting."""
    assert compute_alerts(None) == []


def test_alerts_computed_is_false_until_alerts_is_read():
    """The non-triggering check must not itself trigger the computation."""
    mol = Chem.MolFromSmiles("CCO")
    record = MoleculeRecord(mol=mol, name="Ethanol")
    assert record.alerts_computed is False
    _ = record.alerts
    assert record.alerts_computed is True


def test_invalidate_alerts_forces_recompute():
    mol = Chem.MolFromSmiles("CCO")
    record = MoleculeRecord(mol=mol, name="Ethanol")
    _ = record.alerts
    assert record.alerts_computed is True
    record.invalidate_alerts()
    assert record.alerts_computed is False


def test_compute_alerts_for_records_fills_the_cache_in_place():
    records = [
        MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="ethanol"),
        MoleculeRecord(mol=Chem.MolFromSmiles("O=C1C=CC(=O)C=C1"), name="quinone"),
    ]
    assert all(not r.alerts_computed for r in records)

    report = compute_alerts_for_records(records)

    assert all(r.alerts_computed for r in records)
    assert report.computed == 2
    assert report.reused == 0
    assert report.with_alerts == 1  # only the quinone triggers a warning
    assert report.n_records == 2


def test_compute_alerts_for_records_reuses_already_computed():
    records = [MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="ethanol")]
    compute_alerts_for_records(records)  # first pass computes it

    report = compute_alerts_for_records(records)  # second pass should reuse

    assert report.computed == 0
    assert report.reused == 1


def test_compute_alerts_for_records_recompute_forces_a_fresh_check():
    records = [MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="ethanol")]
    compute_alerts_for_records(records)

    report = compute_alerts_for_records(records, recompute=True)

    assert report.computed == 1
    assert report.reused == 0


def test_compute_alerts_for_records_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [
        MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="a"),
        MoleculeRecord(mol=Chem.MolFromSmiles("CCN"), name="b"),
    ]
    compute_alerts_for_records(records, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (2, 2)
