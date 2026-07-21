"""Tests for the molecular standardization pipeline (pure RDKit, no Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.standardizer import (
    StandardizationOptions,
    standardize_records,
)


def _record(smiles: str, name: str, **props) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return MoleculeRecord(mol=mol, name=name, properties=props)


def test_salt_stripping():
    report = standardize_records(
        [_record("c1ccccc1.Cl", "benzene-HCl")],
        StandardizationOptions(),
    )
    assert report.records[0].smiles == "c1ccccc1"
    assert report.n_changed == 1
    assert "strip-salts" in report.changed[0].steps


def test_charge_neutralization():
    report = standardize_records(
        [_record("CC(=O)[O-]", "acetate")],
        StandardizationOptions(strip_salts=False),
    )
    assert report.records[0].smiles == "CC(=O)O"
    assert "neutralize" in report.changed[0].steps


def test_tautomer_canonicalization_merges_forms():
    # 2-hydroxypyridine and 2-pyridone are tautomers of one compound.
    options = StandardizationOptions(canonicalize_tautomer=True)
    report = standardize_records(
        [_record("Oc1ccccn1", "hydroxy-form"), _record("O=c1cccc[nH]1", "oxo-form")],
        options,
    )
    # After canonicalization both collapse to one form → one is a duplicate.
    assert report.n_records == 1
    assert report.duplicates_removed == 1


def test_duplicate_removal_keeps_first():
    report = standardize_records(
        [_record("CCO", "ethanol-a"), _record("OCC", "ethanol-b"), _record("CCN", "amine")],
        StandardizationOptions(),
    )
    assert report.n_records == 2
    assert report.duplicates_removed == 1
    assert report.records[0].name == "ethanol-a"  # first occurrence wins


def test_duplicates_kept_when_disabled():
    report = standardize_records(
        [_record("CCO", "a"), _record("CCO", "b")],
        StandardizationOptions(remove_duplicates=False),
    )
    assert report.n_records == 2
    assert report.duplicates_removed == 0


def test_unchanged_records_are_reused_not_copied():
    records = [_record("CCO", "ethanol")]
    report = standardize_records(records, StandardizationOptions())
    assert report.records[0] is records[0]  # identity: untouched record reused
    assert report.n_changed == 0


def test_name_source_and_properties_preserved_on_change():
    record = _record("CC(=O)[O-]", "acetate", assay="A1")
    report = standardize_records([record], StandardizationOptions())
    new = report.records[0]
    assert new.name == "acetate"
    assert new.properties == {"assay": "A1"}
    assert new is not record  # changed molecule → new record object


def test_input_records_never_mutated():
    record = _record("c1ccccc1.Cl", "benzene-HCl")
    before = record.smiles
    standardize_records([record], StandardizationOptions())
    assert record.smiles == before


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record("CCO", f"m{i}") for i in range(5)]
    standardize_records(
        records,
        StandardizationOptions(remove_duplicates=False),
        progress=lambda d, t: calls.append((d, t)),
    )
    assert calls[-1] == (5, 5)
