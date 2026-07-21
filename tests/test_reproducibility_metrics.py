"""Tests for dataset-level reproducibility metrics."""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.reproducibility.divergence import analyze_divergence
from wawekit.services.reproducibility.metrics import compute_metrics
from wawekit.services.reproducibility.protocol import (
    DEFAULT_PROTOCOLS,
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
    StandardOp,
)


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_all_agree_gives_perfect_reproducibility():
    records = [("benzene", _mol("c1ccccc1")), ("aspirin", _mol("CC(=O)Oc1ccccc1C(=O)O"))]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)
    metrics = compute_metrics(run)
    assert metrics.smiles_reproducibility == 1.0
    assert metrics.inchikey_reproducibility == 1.0
    assert metrics.n_labile == 0


def test_score_reflects_divergence_fraction():
    records = [
        ("benzene", _mol("c1ccccc1")),  # agrees
        ("benzene-HCl", _mol("c1ccccc1.Cl")),  # diverges
        ("aspirin", _mol("CC(=O)Oc1ccccc1C(=O)O")),  # agrees
        ("acetate-Na", _mol("CC(=O)[O-].[Na+]")),  # diverges
    ]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)
    metrics = compute_metrics(run)
    assert metrics.smiles_reproducibility == 0.5  # 2 of 4 diverge


def test_inchikey_score_can_exceed_smiles_score():
    # The R1 finding at dataset scale: 2-hydroxypyridine is SMILES-labile but
    # InChIKey-stable, so the InChIKey reproducibility score should be higher.
    records = [("2-OH-pyridine", _mol("Oc1ccccn1"))]
    run = analyze_divergence(records, (PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE))
    metrics = compute_metrics(run)
    assert metrics.smiles_reproducibility == 0.0
    assert metrics.inchikey_reproducibility == 1.0


def test_pairwise_agreement_has_one_entry_per_protocol_pair():
    records = [("benzene", _mol("c1ccccc1"))]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)  # 3 protocols
    metrics = compute_metrics(run)
    assert len(metrics.pairwise) == 3  # C(3,2) = 3 pairs


def test_similar_protocols_agree_more_than_dissimilar_ones():
    # ChEMBL-like and Aggressive differ by only 3 ops; Minimal vs Aggressive
    # differ by 7 — the closer pair should show >= agreement on this mixed set.
    records = [
        ("benzene", _mol("c1ccccc1")),
        ("benzene-HCl", _mol("c1ccccc1.Cl")),
        ("2-OH-pyridine", _mol("Oc1ccccn1")),
        ("acetate-Na", _mol("CC(=O)[O-].[Na+]")),
    ]
    run = analyze_divergence(records, (PRESET_MINIMAL, PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE))
    metrics = compute_metrics(run)
    close_pair = next(
        p for p in metrics.pairwise if {p.protocol_a, p.protocol_b} == {"ChEMBL-like", "Aggressive"}
    )
    far_pair = next(
        p for p in metrics.pairwise if {p.protocol_a, p.protocol_b} == {"Minimal", "Aggressive"}
    )
    assert close_pair.smiles_agreement >= far_pair.smiles_agreement


def test_cause_spectrum_is_a_fraction_of_labile_molecules():
    records = [("2-OH-pyridine", _mol("Oc1ccccn1"))]
    run = analyze_divergence(records, (PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE))
    metrics = compute_metrics(run)
    # This molecule is labile and its cause is tautomer canonicalization.
    assert metrics.cause_spectrum[StandardOp.CANONICAL_TAUTOMER] == 1.0


def test_empty_dataset_gives_perfect_default_metrics():
    run = analyze_divergence([], DEFAULT_PROTOCOLS)
    metrics = compute_metrics(run)
    assert metrics.n_molecules == 0
    assert metrics.smiles_reproducibility == 1.0
    assert metrics.pairwise == []


def test_n_labile_is_the_exact_union_count_not_a_score_round_trip():
    # Regression: n_labile used to be derived as round(n * (1 - min(scores))),
    # which is the LARGER of the two per-identity labile counts — not the union
    # of "labile under either identity" that is_labile actually means. Build a
    # run where the two disagree and pin the true count.
    from wawekit.services.reproducibility.divergence import DivergenceRun, MoleculeDivergence
    from wawekit.services.reproducibility.protocol import StandardForm

    def _form(protocol: str, smiles: str, inchikey: str) -> StandardForm:
        return StandardForm(protocol=protocol, smiles=smiles, inchikey=inchikey)

    run = DivergenceRun(
        protocols=(PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE),
        results=[
            # SMILES-labile only (the tautomer case: InChIKey absorbs it).
            MoleculeDivergence(
                name="smiles-only",
                forms=(_form("A", "Oc1ccccn1", "K1"), _form("B", "O=c1cccc[nH]1", "K1")),
                smiles_agree=False,
                inchikey_agree=True,
            ),
            # InChIKey-labile only (e.g. InChI failed for one form).
            MoleculeDivergence(
                name="inchikey-only",
                forms=(_form("A", "CCO", "K2"), _form("B", "CCO", "K3")),
                smiles_agree=True,
                inchikey_agree=False,
            ),
            MoleculeDivergence(
                name="stable",
                forms=(_form("A", "c1ccccc1", "K4"), _form("B", "c1ccccc1", "K4")),
                smiles_agree=True,
                inchikey_agree=True,
            ),
        ],
    )
    metrics = compute_metrics(run)
    # Each identity has 1 labile of 3, but the union is 2 distinct molecules.
    # The old formula reported round(3 * (1 - 2/3)) == 1 — false information.
    assert run.n_labile == 2
    assert metrics.n_labile == 2


def test_two_failed_protocols_do_not_count_as_pairwise_agreement():
    # Regression: a molecule both protocols FAILED on has two empty-string
    # forms, which used to compare equal and inflate pairwise agreement.
    from wawekit.services.reproducibility.divergence import DivergenceRun, MoleculeDivergence
    from wawekit.services.reproducibility.protocol import StandardForm

    failed_a = StandardForm(protocol="A", smiles="", inchikey="", error="boom")
    failed_b = StandardForm(protocol="B", smiles="", inchikey="", error="boom")
    ok_a = StandardForm(protocol="A", smiles="CCO", inchikey="K1")
    ok_b = StandardForm(protocol="B", smiles="CCO", inchikey="K1")

    run = DivergenceRun(
        protocols=(PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE),
        results=[
            MoleculeDivergence(
                name="both-failed",
                forms=(failed_a, failed_b),
                smiles_agree=True,
                inchikey_agree=True,
            ),
            MoleculeDivergence(
                name="fine", forms=(ok_a, ok_b), smiles_agree=True, inchikey_agree=True
            ),
        ],
    )
    metrics = compute_metrics(run)
    # Only the one valid comparison counts; the double-failure adds nothing.
    assert metrics.pairwise[0].smiles_agreement == 1.0
    assert metrics.pairwise[0].inchikey_agreement == 1.0
    assert metrics.n_with_failures == 1
