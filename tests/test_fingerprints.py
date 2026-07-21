"""Tests for fingerprint computation and the fingerprint model (pure, no Qt)."""

from __future__ import annotations

from rdkit import Chem, DataStructs

from wawekit.models.fingerprints import (
    MACCS_N_BITS,
    FingerprintKind,
    FingerprintOptions,
)
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.fingerprints import (
    compute_fingerprint,
    compute_fingerprints,
)

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
PARACETAMOL = "CC(=O)Nc1ccc(O)cc1"


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"test data invalid: {smiles}"
    return mol


def _record(smiles: str, name: str) -> MoleculeRecord:
    return MoleculeRecord(mol=_mol(smiles), name=name)


# ------------------------------------------------------------------- kinds
def test_morgan_has_requested_bit_size():
    fp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(n_bits=1024))
    assert fp.n_bits == 1024
    assert 0 < fp.n_on_bits < 1024


def test_maccs_has_fixed_size_regardless_of_requested_bits():
    fp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(kind=FingerprintKind.MACCS))
    assert fp.n_bits == MACCS_N_BITS


def test_rdkit_path_fingerprint_computes():
    fp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(kind=FingerprintKind.RDKIT))
    assert fp.n_bits == 2048
    assert fp.n_on_bits > 0


def test_radius_changes_the_bits():
    r2 = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(radius=2))
    r3 = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(radius=3))
    # A larger radius captures more fragments, so more bits get set.
    assert r3.n_on_bits > r2.n_on_bits
    assert not r2.is_comparable_to(r3)


def test_features_flag_produces_a_different_fingerprint():
    ecfp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(use_features=False))
    fcfp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions(use_features=True))
    assert ecfp.bits != fcfp.bits
    assert not ecfp.is_comparable_to(fcfp)


def test_density_and_summary():
    fp = compute_fingerprint(_mol(ASPIRIN), FingerprintOptions())
    assert fp.density == fp.n_on_bits / fp.n_bits
    assert fp.summary == f"Morgan · {fp.n_on_bits} on"


# ---------------------------------------------------- options normalization
def test_maccs_ignores_irrelevant_parameters():
    # Radius/bits/features never reach MACCS, so they must not affect identity.
    a = FingerprintOptions(kind=FingerprintKind.MACCS, radius=2, n_bits=2048).normalized()
    b = FingerprintOptions(kind=FingerprintKind.MACCS, radius=5, n_bits=1024).normalized()
    assert a == b
    assert a.n_bits == MACCS_N_BITS


def test_rdkit_ignores_radius_but_not_bits():
    assert FingerprintOptions(kind=FingerprintKind.RDKIT, radius=2).normalized() == (
        FingerprintOptions(kind=FingerprintKind.RDKIT, radius=4).normalized()
    )
    assert FingerprintOptions(kind=FingerprintKind.RDKIT, n_bits=1024).normalized() != (
        FingerprintOptions(kind=FingerprintKind.RDKIT, n_bits=2048).normalized()
    )


def test_morgan_keeps_parameters_that_matter():
    assert FingerprintOptions(radius=2).normalized() != FingerprintOptions(radius=3).normalized()
    assert FingerprintOptions(n_bits=1024).normalized() != (
        FingerprintOptions(n_bits=2048).normalized()
    )


def test_options_accept_a_plain_string_kind():
    # Module 15 will load options from a settings file, where `kind` is a plain
    # string. StrEnum compares equal by value, so this must behave identically.
    from_config = FingerprintOptions(kind="MACCS")
    assert from_config.normalized().n_bits == MACCS_N_BITS
    assert from_config.label == "MACCS"
    assert compute_fingerprint(_mol(ASPIRIN), from_config).n_bits == MACCS_N_BITS


def test_labels():
    assert FingerprintOptions().label == "Morgan r2 · 2048b"
    assert FingerprintOptions(use_features=True).label == "FCFP r2 · 2048b"
    assert FingerprintOptions(kind=FingerprintKind.MACCS).label == "MACCS"
    assert FingerprintOptions(kind=FingerprintKind.RDKIT).label == "RDKit · 2048b"


# ------------------------------------------------------------------ caching
def test_computes_and_caches_in_place():
    records = [_record("CCO", "ethanol")]
    report = compute_fingerprints(records)
    assert report.computed == 1
    assert report.reused == 0
    assert records[0].fingerprint is not None
    assert report.records[0] is records[0]


def test_second_run_with_same_options_reuses():
    records = [_record("CCO", "ethanol")]
    compute_fingerprints(records, FingerprintOptions(radius=2))
    first = records[0].fingerprint
    report = compute_fingerprints(records, FingerprintOptions(radius=2))
    assert report.reused == 1
    assert report.computed == 0
    assert records[0].fingerprint is first


def test_changed_options_force_recompute_so_dataset_never_mixes():
    records = [_record("CCO", "ethanol")]
    compute_fingerprints(records, FingerprintOptions(radius=2))
    report = compute_fingerprints(records, FingerprintOptions(radius=3))
    assert report.computed == 1
    assert report.reused == 0
    assert records[0].fingerprint.options.radius == 3


def test_recompute_flag_forces_recalculation():
    records = [_record("CCO", "ethanol")]
    compute_fingerprints(records)
    report = compute_fingerprints(records, recompute=True)
    assert report.computed == 1
    assert report.reused == 0


def test_report_records_the_options_used():
    records = [_record("CCO", "ethanol")]
    report = compute_fingerprints(records, FingerprintOptions(kind=FingerprintKind.MACCS))
    assert report.options.kind == FingerprintKind.MACCS
    assert report.options.n_bits == MACCS_N_BITS  # normalized


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record("CCO", f"m{i}") for i in range(4)]
    compute_fingerprints(records, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (4, 4)


# ------------------------------------------------- comparability / Module 7
def test_same_options_are_comparable_and_tanimoto_works():
    aspirin = _record(ASPIRIN, "aspirin")
    paracetamol = _record(PARACETAMOL, "paracetamol")
    compute_fingerprints([aspirin, paracetamol])

    assert aspirin.fingerprint.is_comparable_to(paracetamol.fingerprint)
    similarity = DataStructs.TanimotoSimilarity(
        aspirin.fingerprint.bits, paracetamol.fingerprint.bits
    )
    assert 0.0 < similarity < 1.0


def test_identical_molecules_have_tanimoto_one():
    a = _record(ASPIRIN, "a")
    b = _record(ASPIRIN, "b")
    compute_fingerprints([a, b])
    assert DataStructs.TanimotoSimilarity(a.fingerprint.bits, b.fingerprint.bits) == 1.0


def test_bulk_tanimoto_accepts_our_bit_vectors():
    # This is the call Module 7's similarity search will make; keeping RDKit's
    # native ExplicitBitVect is what lets it work with no conversion.
    records = [_record(ASPIRIN, "aspirin"), _record(PARACETAMOL, "paracetamol")]
    compute_fingerprints(records)
    scores = DataStructs.BulkTanimotoSimilarity(
        records[0].fingerprint.bits, [r.fingerprint.bits for r in records]
    )
    assert scores[0] == 1.0
    assert len(scores) == 2
