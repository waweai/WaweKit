"""Tests for CSV/SDF export (pure RDKit/stdlib, no Qt)."""

from __future__ import annotations

import csv

from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.descriptors import compute_descriptors
from wawekit.services.io.molecule_exporter import export_csv, export_sdf


def _record(smiles: str, name: str, **props) -> MoleculeRecord:
    return MoleculeRecord(mol=Chem.MolFromSmiles(smiles), name=name, properties=props)


def test_export_csv_has_header_and_a_row_per_record(tmp_path):
    records = [_record("CCO", "ethanol"), _record("c1ccccc1", "benzene")]
    path = tmp_path / "out.csv"
    n = export_csv(records, path)

    assert n == 2
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0][0] == "Name" and "SMILES" in rows[0]
    assert len(rows) == 3  # header + 2 records
    assert rows[1][0] == "ethanol"


def test_export_csv_leaves_uncomputed_descriptors_blank(tmp_path):
    records = [_record("CCO", "ethanol")]
    path = tmp_path / "blank.csv"
    export_csv(records, path)
    rows = list(csv.reader(path.open(encoding="utf-8")))
    mw_index = rows[0].index("MW")
    assert rows[1][mw_index] == ""  # descriptors not computed → blank


def test_export_csv_includes_computed_descriptors(tmp_path):
    records = [_record("CC(=O)Oc1ccccc1C(=O)O", "aspirin")]
    compute_descriptors(records)
    path = tmp_path / "desc.csv"
    export_csv(records, path)
    rows = list(csv.reader(path.open(encoding="utf-8")))
    mw_index = rows[0].index("MW")
    assert rows[1][mw_index] == "180.16"


def test_export_sdf_round_trips_and_carries_tags(tmp_path):
    records = [_record("CC(=O)Oc1ccccc1C(=O)O", "aspirin", assay="A1")]
    compute_descriptors(records)
    path = tmp_path / "out.sdf"
    n = export_sdf(records, path)

    assert n == 1
    supplier = Chem.SDMolSupplier(str(path))
    mols = [m for m in supplier if m is not None]
    assert len(mols) == 1
    assert mols[0].GetProp("_Name") == "aspirin"
    assert mols[0].GetProp("assay") == "A1"  # source property preserved
    assert mols[0].HasProp("MW")  # computed descriptor written as a tag


def test_export_sdf_does_not_mutate_the_record_mol(tmp_path):
    record = _record("CCO", "ethanol")
    before = record.mol.GetNumAtoms()
    export_sdf([record], tmp_path / "x.sdf")
    assert record.mol.GetNumAtoms() == before
    assert not record.mol.HasProp("_Name") or record.mol.GetProp("_Name") != "ethanol"
