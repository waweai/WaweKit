"""Tests for the quick-filter query language and proxy predicate."""

from __future__ import annotations

from rdkit import Chem

from wawekit.gui.widgets.molecule_filter import (
    InvalidFilter,
    NumericFilter,
    SimilarityFilter,
    TextFilter,
    parse_filter,
)
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.descriptors import compute_descriptors
from wawekit.services.chemistry.similarity import SimilarityRequest, search_similar


def _record(smiles: str, name: str) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return MoleculeRecord(mol=mol, name=name)


# ------------------------------------------------------------------ parsing
def test_empty_query_means_accept_everything():
    assert parse_filter("") is None
    assert parse_filter("   ") is None


def test_plain_text_is_a_text_filter():
    f = parse_filter("aspirin")
    assert isinstance(f, TextFilter)
    assert f.text == "aspirin"


def test_comparison_is_a_numeric_filter():
    f = parse_filter("MW < 500")
    assert isinstance(f, NumericFilter)
    assert f.spec.key == "MW"
    assert f.op == "<"
    assert f.value == 500.0


def test_all_operators_parse():
    for op in ("<", "<=", ">", ">=", "=", "==", "!="):
        f = parse_filter(f"LogP {op} 2")
        assert isinstance(f, NumericFilter)
        assert f.op == op


def test_negative_and_decimal_values_parse():
    f = parse_filter("LogP >= -0.5")
    assert isinstance(f, NumericFilter)
    assert f.value == -0.5


def test_case_insensitive_descriptor_token():
    assert isinstance(parse_filter("mw < 300"), NumericFilter)


def test_unknown_descriptor_is_invalid():
    f = parse_filter("Bogus > 3")
    assert isinstance(f, InvalidFilter)
    assert "Bogus" in f.reason


def test_unknown_term_message_advertises_similarity_too():
    assert "Sim" in parse_filter("Bogus > 3").reason


def test_incomplete_comparison_is_invalid():
    f = parse_filter("MW >")
    assert isinstance(f, InvalidFilter)


# --------------------------------------------------------------- predicates
def test_text_filter_matches_name_and_smiles():
    rec = _record("CCO", "ethanol")
    assert TextFilter("eth").matches(rec) is True  # name
    assert TextFilter("cco").matches(rec) is True  # SMILES, case-insensitive
    assert TextFilter("benzene").matches(rec) is False


def test_numeric_filter_hides_records_without_descriptors():
    rec = _record("CCO", "ethanol")  # descriptors not computed yet
    f = parse_filter("MW < 500")
    assert f.matches(rec) is False


def test_numeric_filter_compares_after_compute():
    rec = _record("CCO", "ethanol")  # MW ~46
    compute_descriptors([rec])
    assert parse_filter("MW < 100").matches(rec) is True
    assert parse_filter("MW > 100").matches(rec) is False


def test_lipinski_equals_zero_selects_passing_molecule():
    rec = _record("CC(=O)Oc1ccccc1C(=O)O", "aspirin")
    compute_descriptors([rec])
    assert parse_filter("Lipinski = 0").matches(rec) is True
    assert parse_filter("Lipinski != 0").matches(rec) is False


# -------------------------------------------------------- similarity (Mod 7)
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"


def _searched(smiles: str, name: str) -> MoleculeRecord:
    """Return a record carrying a real score against aspirin."""
    rec = _record(smiles, name)
    query = _record(ASPIRIN, "aspirin")
    search_similar([rec], SimilarityRequest(query_mol=query.mol, query_name="aspirin"))
    return rec


def test_sim_token_is_a_similarity_filter():
    f = parse_filter("Sim >= 0.7")
    assert isinstance(f, SimilarityFilter)
    assert f.op == ">="
    assert f.value == 0.7


def test_similarity_token_spellings_and_case():
    for query in ("sim > 0.5", "Sim > 0.5", "similarity > 0.5", "SIMILARITY > 0.5"):
        assert isinstance(parse_filter(query), SimilarityFilter)


def test_similarity_filter_hides_records_that_were_never_scored():
    rec = _record("CCO", "ethanol")  # no search has run
    assert parse_filter("Sim >= 0.5").matches(rec) is False


def test_similarity_filter_compares_after_a_search():
    rec = _searched(ASPIRIN, "aspirin")  # identical to the query → 1.0
    assert parse_filter("Sim >= 0.99").matches(rec) is True
    assert parse_filter("Sim < 0.99").matches(rec) is False


def test_similarity_filter_excludes_a_dissimilar_molecule():
    rec = _searched("OCC1OC(O)C(O)C(O)C1O", "glucose")
    assert parse_filter("Sim >= 0.7").matches(rec) is False
    assert parse_filter("Sim < 0.7").matches(rec) is True
