"""Tests for scaffold computation and grouping (pure RDKit, no Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation
from wawekit.services.chemistry.scaffolds import (
    compute_scaffold,
    compute_scaffolds,
    group_scaffolds,
)


def _record(smiles: str, name: str) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return MoleculeRecord(mol=mol, name=name)


def test_ring_molecule_has_scaffold():
    result = compute_scaffold(Chem.MolFromSmiles("CC(=O)Nc1ccccc1"))  # acetanilide
    assert result.has_ring_system
    # The Murcko scaffold of acetanilide is benzene.
    assert result.murcko_smiles == "c1ccccc1"


def test_acyclic_molecule_has_no_scaffold():
    result = compute_scaffold(Chem.MolFromSmiles("CCO"))  # ethanol
    assert not result.has_ring_system
    assert result.murcko_smiles == ""
    assert result.generic_smiles == ""


def test_generic_framework_merges_heteroatom_rings():
    # Pyridine and benzene are different exact scaffolds …
    pyridine = compute_scaffold(Chem.MolFromSmiles("c1ccncc1"))
    benzene = compute_scaffold(Chem.MolFromSmiles("c1ccccc1"))
    assert pyridine.murcko_smiles != benzene.murcko_smiles
    # … but the same generic framework (all-carbon six-ring).
    assert pyridine.generic_smiles == benzene.generic_smiles


def test_smiles_for_switches_representation():
    result = compute_scaffold(Chem.MolFromSmiles("c1ccncc1"))
    assert result.smiles_for(ScaffoldRepresentation.MURCKO) == result.murcko_smiles
    assert result.smiles_for(ScaffoldRepresentation.GENERIC) == result.generic_smiles


def test_compute_scaffolds_caches_in_place_and_reuses():
    records = [_record("c1ccccc1", "benzene"), _record("CCO", "ethanol")]
    report = compute_scaffolds(records)
    assert report.computed == 2
    assert report.reused == 0
    assert records[0].scaffold is not None
    assert records[0] is report.records[0]  # same object, cached in place

    # Second run reuses the cache.
    again = compute_scaffolds(records)
    assert again.computed == 0
    assert again.reused == 2


def test_recompute_forces_recalculation():
    records = [_record("c1ccccc1", "benzene")]
    compute_scaffolds(records)
    report = compute_scaffolds(records, recompute=True)
    assert report.computed == 1
    assert report.reused == 0


def test_group_by_murcko_collects_shared_cores():
    records = [
        _record("CC(=O)Nc1ccccc1", "acetanilide"),
        _record("Nc1ccccc1", "aniline"),
        _record("Cc1ccncc1", "4-methylpyridine"),
        _record("CCO", "ethanol"),
    ]
    compute_scaffolds(records)
    groups = group_scaffolds(records, ScaffoldRepresentation.MURCKO)

    # benzene {acetanilide, aniline}, pyridine {4-methylpyridine}, acyclic {ethanol}
    assert len(groups) == 3
    # Ranked by size: the two-member benzene group leads.
    assert groups[0].size == 2
    assert groups[0].key == "c1ccccc1"
    # The acyclic group is present and flagged.
    acyclic = [g for g in groups if g.is_acyclic]
    assert len(acyclic) == 1
    assert acyclic[0].members[0].name == "ethanol"


def test_generic_grouping_is_coarser_than_murcko():
    records = [_record("c1ccccc1", "benzene"), _record("c1ccncc1", "pyridine")]
    compute_scaffolds(records)
    murcko = group_scaffolds(records, ScaffoldRepresentation.MURCKO)
    generic = group_scaffolds(records, ScaffoldRepresentation.GENERIC)
    assert len(murcko) == 2  # distinct exact scaffolds
    assert len(generic) == 1  # one shared framework


def test_grouping_skips_uncomputed_records():
    records = [_record("c1ccccc1", "benzene")]  # scaffold not computed
    assert group_scaffolds(records) == []


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record("c1ccccc1", f"m{i}") for i in range(4)]
    compute_scaffolds(records, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (4, 4)
