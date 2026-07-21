"""Tests for descriptor computation and the descriptor model (pure, no Qt)."""

from __future__ import annotations

import math

import pytest
from rdkit import Chem

from wawekit.models.descriptors import (
    DESCRIPTOR_BY_KEY,
    DESCRIPTOR_SPECS,
    DescriptorSet,
)
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.descriptors import (
    compute_descriptor_set,
    compute_descriptors,
)


def _record(smiles: str, name: str) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return MoleculeRecord(mol=mol, name=name)


def test_aspirin_values_match_known_descriptors():
    ds = compute_descriptor_set(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
    assert ds.molecular_weight == pytest.approx(180.16, abs=0.01)
    assert ds.logp == pytest.approx(1.31, abs=0.05)
    assert ds.tpsa == pytest.approx(63.6, abs=0.1)
    assert ds.h_bond_donors == 1
    assert ds.h_bond_acceptors == 3
    assert ds.rotatable_bonds == 2
    assert ds.ring_count == 1


def test_lipinski_pass_for_drug_like_molecule():
    ds = compute_descriptor_set(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
    assert ds.lipinski_violations == 0
    assert ds.passes_lipinski is True


def test_lipinski_counts_each_broken_threshold():
    # All four limits deliberately broken: huge MW/logP, many donors/acceptors.
    ds = DescriptorSet(
        molecular_weight=800.0,
        logp=7.5,
        tpsa=200.0,
        h_bond_donors=8,
        h_bond_acceptors=15,
        rotatable_bonds=20,
        ring_count=4,
    )
    assert ds.lipinski_violations == 4
    assert ds.passes_lipinski is False


def test_one_violation_still_passes():
    ds = DescriptorSet(
        molecular_weight=600.0,  # only this exceeds its limit
        logp=3.0,
        tpsa=80.0,
        h_bond_donors=2,
        h_bond_acceptors=5,
        rotatable_bonds=4,
        ring_count=2,
    )
    assert ds.lipinski_violations == 1
    assert ds.passes_lipinski is True


def test_compute_descriptors_caches_on_record_in_place():
    records = [_record("CCO", "ethanol")]
    report = compute_descriptors(records)
    assert report.computed == 1
    assert report.reused == 0
    assert records[0].descriptors is not None  # cached on the same object


def test_second_run_reuses_cached_values():
    records = [_record("CCO", "ethanol")]
    compute_descriptors(records)
    first = records[0].descriptors
    report = compute_descriptors(records)
    assert report.reused == 1
    assert report.computed == 0
    assert records[0].descriptors is first  # not recomputed


def test_recompute_flag_forces_recalculation():
    records = [_record("CCO", "ethanol")]
    compute_descriptors(records)
    report = compute_descriptors(records, recompute=True)
    assert report.computed == 1
    assert report.reused == 0


def test_report_records_are_the_inputs():
    records = [_record("CCO", "ethanol"), _record("CCN", "amine")]
    report = compute_descriptors(records)
    assert report.n_records == 2
    assert report.records[0] is records[0]
    assert report.records[1] is records[1]


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record("CCO", f"m{i}") for i in range(4)]
    compute_descriptors(records, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (4, 4)


def test_specs_cover_every_dataset_field():
    # Every spec's getter must return a real number for a real molecule — this
    # guards against a typo in DESCRIPTOR_SPECS.
    ds = compute_descriptor_set(Chem.MolFromSmiles("c1ccccc1"))
    for spec in DESCRIPTOR_SPECS:
        value = spec.getter(ds)
        assert isinstance(value, (int, float))
        assert not math.isnan(float(value))
        # Every spec's format string must accept its value.
        assert isinstance(spec.fmt.format(value), str)


def test_descriptor_key_lookup_is_case_insensitive():
    assert DESCRIPTOR_BY_KEY["mw"].label == "MW"
    assert DESCRIPTOR_BY_KEY["logp"].key == "LogP"
