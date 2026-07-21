"""Tests for the standardization protocol engine (pure RDKit, no Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.reproducibility.protocol import (
    DEFAULT_PROTOCOLS,
    OPERATION_ORDER,
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
    StandardizationProtocol,
    StandardOp,
    apply_protocol,
    standard_identity,
    standardize,
)


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None, f"bad test SMILES: {smiles}"
    return mol


def test_standard_identity_is_an_inchikey():
    key = standard_identity(_mol("CCO"))
    # 14 block - 10 block - 1 char, e.g. LFQSCWFLJHTTHZ-UHFFFAOYSA-N
    assert len(key) == 27 and key.count("-") == 2


def test_applied_ops_are_in_canonical_order():
    protocol = StandardizationProtocol(
        "x", frozenset({StandardOp.CANONICAL_TAUTOMER, StandardOp.NORMALIZE})
    )
    ops = protocol.applied_ops()
    assert ops == [StandardOp.NORMALIZE, StandardOp.CANONICAL_TAUTOMER]  # order, not set order


def test_fragment_parent_strips_salt():
    form = standardize(_mol("CC(=O)[O-].[Na+]"), PRESET_CHEMBL_LIKE)
    assert form.ok
    assert "." not in form.smiles  # counter-ion removed
    assert "Na" not in form.smiles


def test_minimal_keeps_the_salt_but_chembl_strips_it():
    salt = _mol("c1ccccc1.Cl")
    minimal = standardize(salt, PRESET_MINIMAL)
    chembl = standardize(salt, PRESET_CHEMBL_LIKE)
    # The two protocols disagree on this molecule's identity (salt handling).
    assert minimal.inchikey != chembl.inchikey


def test_tautomer_operation_changes_the_smiles_form():
    # 2-hydroxypyridine: the canonical-tautomer op rewrites it to the pyridone form.
    hydroxy = _mol("Oc1ccccn1")
    without = standardize(hydroxy, PRESET_CHEMBL_LIKE)  # no tautomer op
    with_taut = standardize(hydroxy, PRESET_AGGRESSIVE)  # has tautomer op
    assert without.smiles != with_taut.smiles  # the SMILES identity diverges


def test_inchikey_masks_the_tautomer_divergence_that_smiles_reveals():
    # A key methodological finding: InChI normalizes tautomers internally, so the
    # InChIKey is tautomer-robust here even though the SMILES is not. The study
    # therefore measures agreement on BOTH identities — they can disagree.
    hydroxy = _mol("Oc1ccccn1")
    without = standardize(hydroxy, PRESET_CHEMBL_LIKE)
    with_taut = standardize(hydroxy, PRESET_AGGRESSIVE)
    assert without.smiles != with_taut.smiles  # SMILES-identity: they diverge
    assert without.inchikey == with_taut.inchikey  # InChIKey-identity: they agree


def test_remove_isotopes_changes_identity():
    deuterated = _mol("[2H]OC")  # methanol-d1
    keep = standardize(deuterated, PRESET_CHEMBL_LIKE)  # keeps isotope
    strip = standardize(deuterated, PRESET_AGGRESSIVE)  # removes isotope
    assert keep.inchikey != strip.inchikey


def test_remove_stereo_flattens():
    chiral = _mol("C[C@H](N)C(=O)O")  # L-alanine
    with_op = StandardizationProtocol("s", frozenset({StandardOp.REMOVE_STEREO}))
    flat = standardize(chiral, with_op)
    original = standard_identity(chiral)
    # Stereo lives in the InChIKey's second block; removing it changes the key.
    assert flat.inchikey != original


def test_with_op_toggles_and_renames():
    added = PRESET_MINIMAL.with_op(StandardOp.UNCHARGE, True)
    assert added.has(StandardOp.UNCHARGE)
    assert added.name.endswith("+uncharge")

    removed = PRESET_AGGRESSIVE.with_op(StandardOp.CANONICAL_TAUTOMER, False)
    assert not removed.has(StandardOp.CANONICAL_TAUTOMER)
    assert removed.name.endswith("-canonical_tautomer")


def test_apply_protocol_does_not_mutate_input():
    salt = _mol("CC(=O)[O-].[Na+]")
    before = Chem.MolToSmiles(salt)
    apply_protocol(salt, PRESET_AGGRESSIVE)
    assert Chem.MolToSmiles(salt) == before


def test_presets_have_expected_operations():
    assert PRESET_MINIMAL.operations == frozenset({StandardOp.NORMALIZE})
    assert StandardOp.CANONICAL_TAUTOMER not in PRESET_CHEMBL_LIKE.operations
    assert PRESET_AGGRESSIVE.operations == frozenset(OPERATION_ORDER)
    assert DEFAULT_PROTOCOLS == (PRESET_MINIMAL, PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE)


def test_standardize_handles_agreement_across_a_trivial_molecule():
    # A plain, unambiguous molecule standardizes identically under all protocols.
    keys = {standardize(_mol("c1ccccc1"), p).inchikey for p in DEFAULT_PROTOCOLS}
    assert len(keys) == 1  # benzene: everyone agrees
