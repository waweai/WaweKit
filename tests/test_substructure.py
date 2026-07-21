"""Tests for substructure searching (pure RDKit, no Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.models.substructure import SubstructureQuery
from wawekit.services.chemistry.substructure import parse_query, search_substructure


def _records(*smiles_names: tuple[str, str]) -> list[MoleculeRecord]:
    return [MoleculeRecord(mol=Chem.MolFromSmiles(smi), name=name) for smi, name in smiles_names]


def test_parse_query_smarts_and_smiles():
    assert parse_query("c1ccncc1", is_smarts=True) is not None
    assert parse_query("c1ccncc1", is_smarts=False) is not None
    assert parse_query("[NX3][CX3](=O)", is_smarts=True) is not None
    # A SMARTS-only primitive is not valid SMILES.
    assert parse_query("[NX3]", is_smarts=False) is None


def test_parse_query_rejects_garbage():
    assert parse_query("not a query!!!", is_smarts=True) is None
    assert parse_query("", is_smarts=True) is None


def test_search_flags_matches_and_records_atoms():
    records = _records(
        ("c1ccncc1", "pyridine"),
        ("Cc1ccncc1", "methylpyridine"),
        ("c1ccccc1", "benzene"),
    )
    report = search_substructure(records, SubstructureQuery("c1ccncc1", is_smarts=True))

    assert report.matched == 2  # both pyridines
    assert records[0].substructure_match.is_match
    assert records[2].substructure_match is not None
    assert not records[2].substructure_match.is_match  # benzene: searched, no match
    # The pyridine's match highlights its six ring atoms.
    assert len(records[0].substructure_match.atoms) == 6


def test_multiple_matches_are_counted():
    # Biphenyl contains a benzene ring twice.
    records = _records(("c1ccc(-c2ccccc2)cc1", "biphenyl"))
    report = search_substructure(records, SubstructureQuery("c1ccccc1", is_smarts=True))
    assert records[0].substructure_match.n_matches == 2
    assert report.matched == 1


def test_smarts_amide_query():
    records = _records(("CC(=O)Nc1ccccc1", "acetanilide"), ("c1ccccc1", "benzene"))
    report = search_substructure(records, SubstructureQuery("[NX3][CX3](=O)", is_smarts=True))
    assert records[0].substructure_match.is_match
    assert not records[1].substructure_match.is_match
    assert report.matched == 1


def test_invalid_query_raises():
    with pytest.raises(ValueError, match="Invalid"):
        search_substructure(_records(("CCO", "ethanol")), SubstructureQuery("!!bad!!"))


def test_search_clears_stale_match_on_rerun():
    records = _records(("c1ccncc1", "pyridine"))
    search_substructure(records, SubstructureQuery("c1ccncc1"))
    assert records[0].substructure_match.is_match
    # A second search for something absent leaves a no-match hit, not the old one.
    search_substructure(records, SubstructureQuery("S(=O)(=O)N"))
    assert not records[0].substructure_match.is_match


def test_hit_display_and_tooltip():
    records = _records(("c1ccc(-c2ccccc2)cc1", "biphenyl"))
    search_substructure(records, SubstructureQuery("c1ccccc1"))
    hit = records[0].substructure_match
    assert hit.display == "✓ 2"
    assert "match" in hit.tooltip


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = _records(("CCO", "a"), ("c1ccccc1", "b"))
    search_substructure(
        records, SubstructureQuery("c1ccccc1"), progress=lambda d, t: calls.append((d, t))
    )
    assert calls[-1] == (2, 2)
