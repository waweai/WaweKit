"""Tests for the molecule loader service.

These tests author their own input files into pytest's ``tmp_path`` so they are
fully self-contained and exercise the real RDKit parsers — including the
error-recovery paths that matter most with real-world chemical files.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from wawekit.services.io.molecule_loader import (
    SUPPORTED_EXTENSIONS,
    UnsupportedFormatError,
    detect_format,
    file_dialog_filter,
    load_file,
)


def _write_sdf(path: Path, smiles_names: list[tuple[str, str]]) -> None:
    """Author a valid SDF file from (smiles, name) pairs using RDKit."""
    writer = Chem.SDWriter(str(path))
    for smiles, name in smiles_names:
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None, f"test data invalid: {smiles}"
        mol.SetProp("_Name", name)
        mol.SetProp("series", "test")
        writer.write(mol)
    writer.close()


def test_detect_format_known_and_unknown(tmp_path):
    assert detect_format(Path("x.sdf")) == "sdf"
    assert detect_format(Path("x.SMI")) == "smiles"
    with pytest.raises(UnsupportedFormatError):
        detect_format(Path("x.docx"))


def test_file_dialog_filter_mentions_every_extension():
    filt = file_dialog_filter()
    for ext in SUPPORTED_EXTENSIONS:
        assert f"*{ext}" in filt


def test_load_sdf_happy_path(tmp_path):
    path = tmp_path / "mols.sdf"
    _write_sdf(path, [("CCO", "ethanol"), ("c1ccccc1", "benzene"), ("CC(=O)O", "acetic acid")])

    report = load_file(path)

    assert report.fmt == "sdf"
    assert report.n_loaded == 3
    assert report.n_failed == 0
    assert [r.name for r in report.records] == ["ethanol", "benzene", "acetic acid"]
    assert report.records[0].properties["series"] == "test"
    assert report.records[1].formula == "C6H6"
    assert report.records[0].index_in_source == 1
    assert report.records[0].source == path


def test_load_sdf_with_corrupt_record(tmp_path):
    path = tmp_path / "dirty.sdf"
    _write_sdf(path, [("CCO", "ethanol")])
    # Append a garbage record: syntactically delimited but unparseable.
    with path.open("a", encoding="utf-8") as fh:
        fh.write("this is not a molecule\nat all\nM  END\n$$$$\n")

    report = load_file(path)

    assert report.n_loaded == 1
    assert report.n_failed == 1
    assert "record 2" in report.errors[0].location


def test_load_smiles_with_names_comments_and_errors(tmp_path):
    path = tmp_path / "set.smi"
    path.write_text(
        "# a comment line\n"
        "CCO ethanol\n"
        "\n"
        "c1ccccc1 benzene\n"
        "NOT_A_SMILES bad_one\n"
        "CC(C)=O\n",
        encoding="utf-8",
    )

    report = load_file(path)

    assert report.n_loaded == 3
    assert report.n_failed == 1
    names = [r.name for r in report.records]
    assert names[0] == "ethanol"
    assert names[1] == "benzene"
    assert names[2] == "set_6"  # generated fallback: stem + line number
    assert "line 5" in report.errors[0].location


def test_load_smiles_header_hint(tmp_path):
    path = tmp_path / "export.smi"
    path.write_text("smiles name\nCCO ethanol\n", encoding="utf-8")

    report = load_file(path)

    assert report.n_loaded == 1
    assert report.n_failed == 1
    assert "header" in report.errors[0].message


def test_load_single_mol_file(tmp_path):
    path = tmp_path / "aspirin.mol"
    mol = Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O")
    Chem.MolToMolFile(mol, str(path))

    report = load_file(path)

    assert report.n_loaded == 1
    assert report.records[0].formula == "C9H8O4"


def test_load_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_file(tmp_path / "ghost.sdf")


def test_progress_callback_invoked(tmp_path):
    path = tmp_path / "many.smi"
    path.write_text("\n".join(["CCO"] * 250), encoding="utf-8")
    calls: list[tuple[int, int]] = []

    load_file(path, progress=lambda done, total: calls.append((done, total)))

    assert calls, "progress callback was never invoked"
    assert calls[-1] == (250, 250)
