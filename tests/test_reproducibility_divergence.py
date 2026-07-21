"""Tests for divergence analysis and ablation-based cause attribution."""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.reproducibility.divergence import analyze_divergence, analyze_molecule
from wawekit.services.reproducibility.protocol import (
    DEFAULT_PROTOCOLS,
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
    StandardOp,
)


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"bad test SMILES: {smiles}"
    return mol


def test_trivial_molecule_agrees_on_both_identities():
    result = analyze_molecule(_mol("c1ccccc1"), DEFAULT_PROTOCOLS, name="benzene")
    assert result.smiles_agree
    assert result.inchikey_agree
    assert not result.is_labile
    assert result.causes == ()


def test_salt_causes_divergence_on_both_identities():
    result = analyze_molecule(_mol("c1ccccc1.Cl"), DEFAULT_PROTOCOLS, name="benzene-HCl")
    assert not result.smiles_agree
    assert not result.inchikey_agree
    assert result.is_labile
    assert result.n_distinct_smiles >= 2


def test_tautomer_labile_molecule_diverges_only_on_smiles():
    # 2-hydroxypyridine: R1's headline finding, now as a divergence result.
    protocols = (PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE)
    result = analyze_molecule(_mol("Oc1ccccn1"), protocols, name="2-OH-pyridine")
    assert not result.smiles_agree
    assert result.inchikey_agree  # InChI absorbs the tautomer difference
    assert result.is_labile  # labile overall because SMILES disagrees


def test_ablation_attributes_the_tautomer_cause():
    # Compare a protocol WITHOUT the tautomer op against one WITH it — ablating
    # the tautomer operation from the richer protocol should surface it as the
    # cause of the (SMILES-level) divergence.
    result = analyze_molecule(
        _mol("Oc1ccccn1"), (PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE), name="2-OH-pyridine"
    )
    assert StandardOp.CANONICAL_TAUTOMER in result.causes


def test_ablation_attributes_the_fragment_cause_for_a_salt():
    protocols = (PRESET_MINIMAL, PRESET_CHEMBL_LIKE)
    result = analyze_molecule(_mol("CC(=O)[O-].[Na+]"), protocols, name="acetate-Na")
    assert result.is_labile
    # Salt handling is FRAGMENT_PARENT (and often UNCHARGE too); at least one of
    # the ionic-handling operations must be implicated.
    assert result.causes  # something was attributed
    assert {StandardOp.FRAGMENT_PARENT, StandardOp.UNCHARGE} & set(result.causes)


def test_attribute_causes_false_skips_ablation():
    result = analyze_molecule(_mol("c1ccccc1.Cl"), DEFAULT_PROTOCOLS, attribute_causes=False)
    assert result.is_labile
    assert result.causes == ()  # ablation was skipped


def test_analyze_divergence_over_a_dataset():
    records = [
        ("benzene", _mol("c1ccccc1")),
        ("benzene-HCl", _mol("c1ccccc1.Cl")),
        ("2-OH-pyridine", _mol("Oc1ccccn1")),
    ]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)

    assert run.n_molecules == 3
    assert run.n_labile == 2  # benzene-HCl and 2-OH-pyridine
    assert run.n_smiles_labile == 2
    # 2-OH-pyridine agrees under InChIKey, so InChIKey-labile count is lower.
    assert run.n_inchikey_labile < run.n_smiles_labile


def test_cause_counts_tally_across_the_dataset():
    records = [("benzene-HCl", _mol("c1ccccc1.Cl")), ("2-OH-pyridine", _mol("Oc1ccccn1"))]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)
    counts = run.cause_counts()
    assert counts[StandardOp.CANONICAL_TAUTOMER] >= 1  # from the pyridine case
    assert sum(counts.values()) >= 1


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [("a", _mol("CCO")), ("b", _mol("CCN"))]
    analyze_divergence(records, DEFAULT_PROTOCOLS, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (2, 2)


def test_a_protocol_failure_is_not_reported_as_divergence(monkeypatch):
    # Regression: a failed protocol used to contribute its empty SMILES/InChIKey
    # to the agreement sets, flagging the molecule "labile" when nothing
    # actually diverged — and a molecule where EVERY protocol failed compared
    # as perfectly reproducible. Failures are failures, not divergence.
    from wawekit.services.reproducibility import divergence as div_mod
    from wawekit.services.reproducibility.protocol import StandardForm

    def fake_standardize(mol, protocol):
        if protocol.name == "Minimal":
            return StandardForm(protocol=protocol.name, smiles="", inchikey="", error="boom")
        return StandardForm(protocol=protocol.name, smiles="CCO", inchikey="K1")

    monkeypatch.setattr(div_mod, "standardize", fake_standardize)
    result = div_mod.analyze_molecule(_mol("CCO"), DEFAULT_PROTOCOLS, name="ethanol")

    assert not result.is_labile  # the two protocols that ran agree perfectly
    assert result.n_failed == 1
    assert not result.all_failed


def test_all_protocols_failing_is_tracked_not_hidden(monkeypatch):
    from wawekit.services.reproducibility import divergence as div_mod
    from wawekit.services.reproducibility.protocol import StandardForm

    def fake_standardize(mol, protocol):
        return StandardForm(protocol=protocol.name, smiles="", inchikey="", error="boom")

    monkeypatch.setattr(div_mod, "standardize", fake_standardize)
    records = [("bad", _mol("CCO"))]
    run = div_mod.analyze_divergence(records, DEFAULT_PROTOCOLS)

    assert run.results[0].all_failed
    assert run.n_with_failures == 1
