"""Tests for similarity search and the similarity model (pure, no Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.models.fingerprints import FingerprintKind, FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.similarity import SimilarityMetric, SimilarityQuery, SimilarityScore
from wawekit.services.chemistry.fingerprints import compute_fingerprint, compute_fingerprints
from wawekit.services.chemistry.similarity import (
    SimilarityRequest,
    search_similar,
)

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
SALICYLIC_ACID = "O=C(O)c1ccccc1O"  # aspirin minus the acetyl — a close analogue
PARACETAMOL = "CC(=O)Nc1ccc(O)cc1"
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"  # nothing like aspirin


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return mol


def _record(smiles: str, name: str) -> MoleculeRecord:
    return MoleculeRecord(mol=_mol(smiles), name=name)


def _dataset() -> list[MoleculeRecord]:
    return [
        _record(PARACETAMOL, "paracetamol"),
        _record(GLUCOSE, "glucose"),
        _record(ASPIRIN, "aspirin"),
        _record(SALICYLIC_ACID, "salicylic acid"),
    ]


def _request(smiles: str = ASPIRIN, name: str = "aspirin", **kwargs) -> SimilarityRequest:
    return SimilarityRequest(query_mol=_mol(smiles), query_name=name, **kwargs)


# ------------------------------------------------------------------- ranking
def test_query_ranks_first_against_itself():
    records = _dataset()
    report = search_similar(records, _request())
    assert report.ranked[0].name == "aspirin"
    assert report.ranked[0].similarity.value == 1.0


def test_ranked_is_sorted_best_first():
    report = search_similar(_dataset(), _request())
    values = [r.similarity.value for r in report.ranked]
    assert values == sorted(values, reverse=True)


def test_close_analogue_outranks_unrelated_molecule():
    # The chemistry sanity check: salicylic acid is aspirin without the acetyl,
    # glucose is a sugar. If this ever inverts, something is deeply wrong.
    report = search_similar(_dataset(), _request())
    by_name = {r.name: r.similarity.value for r in report.ranked}
    assert by_name["salicylic acid"] > by_name["glucose"]


def test_every_record_is_scored_and_cached_in_place():
    records = _dataset()
    report = search_similar(records, _request())
    assert report.n_scored == len(records)
    assert all(r.similarity is not None for r in records)


def test_top_returns_the_head_of_the_hit_list():
    report = search_similar(_dataset(), _request())
    assert report.top(2) == report.ranked[:2]
    assert len(report.top(2)) == 2


def test_scores_are_bounded():
    report = search_similar(_dataset(), _request())
    assert all(0.0 <= r.similarity.value <= 1.0 for r in report.ranked)


def test_query_absent_from_the_dataset_still_searches():
    # Pasting a SMILES that is nowhere in the library is a normal thing to do.
    records = [_record(PARACETAMOL, "paracetamol"), _record(GLUCOSE, "glucose")]
    report = search_similar(records, _request(ASPIRIN, "pasted aspirin"))
    assert report.n_scored == 2
    assert all(r.similarity.value < 1.0 for r in records)


# -------------------------------------------------------------- provenance
def test_score_carries_the_query_that_produced_it():
    records = _dataset()
    search_similar(records, _request(metric=SimilarityMetric.DICE))
    score = records[0].similarity
    assert score.query.name == "aspirin"
    assert score.query.metric is SimilarityMetric.DICE
    assert score.query.smiles == Chem.MolToSmiles(_mol(ASPIRIN))


def test_query_records_the_normalized_fingerprint_options():
    # MACCS ignores radius, so the query must report the *effective* config —
    # otherwise two identical searches would look like different ones.
    records = _dataset()
    report = search_similar(
        records,
        _request(fingerprint=FingerprintOptions(kind=FingerprintKind.MACCS, radius=5)),
    )
    assert report.query.fingerprint == FingerprintOptions(kind=FingerprintKind.MACCS).normalized()


def test_all_scores_from_one_run_share_one_query():
    records = _dataset()
    search_similar(records, _request())
    queries = {r.similarity.query for r in records}
    assert len(queries) == 1


def test_is_query_molecule_identifies_the_query_row():
    records = _dataset()
    search_similar(records, _request())
    aspirin = next(r for r in records if r.name == "aspirin")
    glucose = next(r for r in records if r.name == "glucose")
    assert aspirin.similarity.is_query_molecule(aspirin.smiles) is True
    assert glucose.similarity.is_query_molecule(glucose.smiles) is False


def test_is_query_molecule_is_not_just_a_perfect_score():
    # A duplicate of the query scores 1.0 and *is* the same molecule; a
    # different molecule that collided would score 1.0 and must not be claimed.
    query = SimilarityQuery(
        smiles=Chem.MolToSmiles(_mol(ASPIRIN)),
        name="aspirin",
        metric=SimilarityMetric.TANIMOTO,
        fingerprint=FingerprintOptions(),
    )
    collision = SimilarityScore(value=1.0, query=query)
    assert collision.is_query_molecule(Chem.MolToSmiles(_mol(GLUCOSE))) is False


def test_query_label_is_readable():
    report = search_similar(_dataset(), _request())
    assert report.query.label == "Tanimoto vs aspirin · Morgan r2 · 2048b"


def test_score_display_is_three_decimals():
    assert SimilarityScore(value=0.8467, query=None).display == "0.847"


# ------------------------------------------------------------------ metrics
@pytest.mark.parametrize("metric", list(SimilarityMetric))
def test_every_metric_runs_and_scores_the_query_one(metric):
    records = _dataset()
    report = search_similar(records, _request(metric=metric))
    assert report.n_scored == len(records)
    assert report.ranked[0].similarity.value == 1.0


def test_dice_scores_at_least_tanimoto_for_the_same_pair():
    # Dice counts the shared bits twice, so 2c/(a+b) >= c/(a+b-c) always.
    tanimoto = search_similar(_dataset(), _request(metric=SimilarityMetric.TANIMOTO))
    dice = search_similar(_dataset(), _request(metric=SimilarityMetric.DICE))
    t_by_name = {r.name: r.similarity.value for r in tanimoto.ranked}
    d_by_name = {r.name: r.similarity.value for r in dice.ranked}
    assert all(d_by_name[name] >= t_by_name[name] for name in t_by_name)


def test_metric_may_arrive_as_a_plain_string():
    # From a Qt QVariant or a Module 15 settings file. StrEnum hashes by value,
    # so the bulk-function lookup resolves — this pins that behaviour.
    records = _dataset()
    report = search_similar(records, _request(metric="Dice"))
    assert report.query.metric is SimilarityMetric.DICE
    assert report.n_scored == len(records)


# ----------------------------------------------------- encoding consistency
def test_search_encodes_the_dataset_when_it_has_no_fingerprints():
    records = _dataset()
    assert all(r.fingerprint is None for r in records)
    report = search_similar(records, _request())
    assert report.fingerprints_computed == len(records)
    assert all(r.fingerprint is not None for r in records)


def test_search_reuses_matching_fingerprints():
    records = _dataset()
    compute_fingerprints(records, FingerprintOptions())
    report = search_similar(records, _request(fingerprint=FingerprintOptions()))
    assert report.fingerprints_computed == 0


def test_search_re_encodes_a_dataset_built_with_other_options():
    # The dataset is MACCS; the search asks for Morgan. Scoring MACCS vectors
    # against a Morgan query would return plausible, meaningless numbers.
    records = _dataset()
    compute_fingerprints(records, FingerprintOptions(kind=FingerprintKind.MACCS))
    report = search_similar(records, _request(fingerprint=FingerprintOptions()))
    assert report.fingerprints_computed == len(records)
    assert all(r.fingerprint.options == FingerprintOptions() for r in records)
    assert report.n_skipped == 0


def test_query_and_dataset_are_always_encoded_the_same_way():
    records = _dataset()
    report = search_similar(records, _request(fingerprint=FingerprintOptions(radius=3)))
    assert report.query.fingerprint.radius == 3
    assert all(r.fingerprint.options == report.query.fingerprint for r in records)


def test_record_that_cannot_be_encoded_is_skipped():
    records = _dataset()
    broken = MoleculeRecord(mol=None, name="broken")  # RDKit will throw on this
    report = search_similar([*records, broken], _request())

    assert broken.similarity is None
    assert report.n_skipped == 1
    assert "broken" in report.skipped[0]
    assert report.n_scored == len(records)


def test_incomparable_leftover_fingerprint_is_skipped_not_scored():
    """The comparability guard is load-bearing, and this is the path that proves it.

    ``compute_fingerprints`` assigns a new vector only on success — a molecule
    RDKit throws on silently *keeps its old fingerprint*. So a MACCS dataset
    re-encoded as Morgan, with one failure in it, leaves one record holding a
    MACCS vector among Morgan ones. RDKit would score it against the Morgan
    query without complaint and return a number that means nothing.
    """
    records = _dataset()
    compute_fingerprints(records, FingerprintOptions(kind=FingerprintKind.MACCS))

    stale = records[1]
    stale.mol = None  # re-encoding will now fail, leaving the MACCS vector behind
    report = search_similar(records, _request(fingerprint=FingerprintOptions()))

    assert stale.fingerprint.options.kind is FingerprintKind.MACCS  # the leftover
    assert stale.similarity is None  # refused, not scored
    assert report.n_skipped == 1
    assert "not comparable" in report.skipped[0]
    assert report.n_scored == len(records) - 1


def test_stale_score_is_cleared_rather_than_left_under_a_new_query():
    # A number from the previous query, sitting in a column headed by a new one,
    # is worse than a blank cell.
    records = _dataset()
    search_similar(records, _request())
    assert records[1].similarity is not None

    records[1].mol = None
    records[1].fingerprint = None
    search_similar(records, _request(PARACETAMOL, "paracetamol"))

    assert records[1].similarity is None


def test_metric_change_alone_rescores_without_re_encoding():
    records = _dataset()
    search_similar(records, _request(metric=SimilarityMetric.TANIMOTO))
    report = search_similar(records, _request(metric=SimilarityMetric.COSINE))
    assert report.fingerprints_computed == 0
    assert all(r.similarity.query.metric is SimilarityMetric.COSINE for r in report.ranked)


# -------------------------------------------- what RDKit does and does not do
def test_rdkit_only_guards_bit_length_not_meaning():
    """Pins why ``is_comparable_to`` exists at all.

    RDKit raises on a length mismatch (Morgan 2048 vs MACCS 167) — that mistake
    is loud and safe. It says nothing about vectors that are the same length and
    mean different things, which is the mistake that actually ships. Every number
    below is in the range a chemist expects; only the first means anything.
    """
    from rdkit import DataStructs

    aspirin, salicylic = _mol(ASPIRIN), _mol(SALICYLIC_ACID)
    morgan_r2 = compute_fingerprint(aspirin, FingerprintOptions())

    truth = DataStructs.TanimotoSimilarity(
        morgan_r2.bits, compute_fingerprint(salicylic, FingerprintOptions()).bits
    )
    assert round(truth, 3) == 0.448

    # Loud: different lengths cannot be compared at all.
    maccs = compute_fingerprint(salicylic, FingerprintOptions(kind=FingerprintKind.MACCS))
    assert not morgan_r2.is_comparable_to(maccs)
    with pytest.raises(ValueError, match="same length"):
        DataStructs.TanimotoSimilarity(morgan_r2.bits, maccs.bits)

    # Silent: same length, different meaning — RDKit answers without complaint.
    for options, expected in (
        (FingerprintOptions(radius=3), 0.394),  # plausible, and wrong
        (FingerprintOptions(kind=FingerprintKind.RDKIT), 0.005),  # a hit looks like noise
        (FingerprintOptions(use_features=True), 0.000),  # a close analogue scores zero
    ):
        other = compute_fingerprint(salicylic, options)
        assert other.n_bits == morgan_r2.n_bits  # same length: RDKit is satisfied
        assert not morgan_r2.is_comparable_to(other)  # we are not
        nonsense = DataStructs.TanimotoSimilarity(morgan_r2.bits, other.bits)
        assert round(nonsense, 3) == expected
        assert nonsense != truth


# ----------------------------------------------------------------- progress
def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = _dataset()
    search_similar(records, _request(), progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (len(records), len(records))


def test_empty_dataset_is_not_an_error():
    report = search_similar([], _request())
    assert report.ranked == []
    assert report.n_scored == 0
