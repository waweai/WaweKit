"""Tests for 3D shape and radial-shell descriptors (pure RDKit, no Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.models.conformers import ConformerOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.shape3d import (
    AtomClass,
    CenterMode,
    ConformerChoice,
    RadialOptions,
    ShellNormalization,
)
from wawekit.services.chemistry.conformers import generate_conformer_set
from wawekit.services.chemistry.shape3d import (
    compute_radial_shells,
    compute_shape_descriptor_set,
    compute_shape_descriptors,
    radial_sensitivity,
)

# Three molecules whose 3D character is unambiguous, so the assertions below can
# be about chemistry rather than about whatever number the code happens to emit.
CHOLESTEROL = "CC(C)CCCC(C)C1CCC2C1(CCC3C2CC=C4C3(CCC(C4)O)C)C"  # all-sp3 steroid
CAFFEINE = "CN1C=NC2=C1C(=O)N(C)C(=O)N2C"  # flat, polar-rimmed heteroaromatic
BENZENE = "c1ccccc1"  # perfectly planar, purely aromatic


def _conf_options(**changes) -> ConformerOptions:
    params = {"n_confs": 4, "random_seed": 1}
    params.update(changes)
    return ConformerOptions(**params)


def _conformers(smiles: str, **changes):
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return generate_conformer_set(mol, _conf_options(**changes))


def _record(smiles: str, name: str) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return MoleculeRecord(mol=mol, name=name)


# --- RadialOptions validation and key naming ------------------------------


def test_shell_radii_must_be_positive_and_increasing():
    with pytest.raises(ValueError):
        RadialOptions(shells=())
    with pytest.raises(ValueError):
        RadialOptions(shells=(3.0, 0.0))
    with pytest.raises(ValueError):
        RadialOptions(shells=(6.0, 3.0))
    with pytest.raises(ValueError):
        RadialOptions(shells=(3.0, 3.0))


def test_descriptor_keys_follow_the_published_convention():
    options = RadialOptions(shells=(3.0, 6.0))
    assert options.key(3.0, AtomClass.SP3_CARBON) == "r3_sp3C_C"
    assert options.key(6.0, AtomClass.AROMATIC_CARBON) == "r6_aroC_C"
    # Six keys: three atom classes across two shells, in a stable order.
    assert options.keys() == [
        "r3_sp3C_C",
        "r3_aroC_C",
        "r3_electronegative_C",
        "r6_sp3C_C",
        "r6_aroC_C",
        "r6_electronegative_C",
    ]


def test_normalization_changes_the_key_suffix():
    assert (
        RadialOptions(normalization=ShellNormalization.PER_ATOM).key(3.0, AtomClass.SP3_CARBON)
        == "r3_sp3C_A"
    )
    assert (
        RadialOptions(normalization=ShellNormalization.COUNT).key(3.0, AtomClass.SP3_CARBON)
        == "r3_sp3C_n"
    )


# --- Radial shells: the chemistry must come out right ---------------------


def test_saturated_steroid_is_all_sp3_and_never_aromatic():
    conf_set = _conformers(CHOLESTEROL)
    _center, values = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions()
    )

    # Cholesterol's core is entirely saturated carbon: every carbon near the
    # centre is sp3, and none is aromatic, under any conformer.
    assert values["r3_sp3C_C"] == pytest.approx(1.0)
    assert values["r3_aroC_C"] == 0.0
    assert values["r6_aroC_C"] == 0.0


def test_benzene_is_all_aromatic_and_never_sp3():
    conf_set = _conformers(BENZENE, n_confs=1)
    _center, values = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions()
    )

    assert values["r3_aroC_C"] == pytest.approx(1.0)
    assert values["r3_sp3C_C"] == 0.0


def test_caffeine_has_electronegative_atoms_at_its_core():
    conf_set = _conformers(CAFFEINE)
    _center, values = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions()
    )

    # The purine core is ringed by N and O, so the inner shell is polar-rich.
    assert values["r3_electronegative_C"] > 0.5
    assert values["r3_sp3C_C"] == 0.0  # the N-methyls sit outside 3 A


def test_centre_of_mass_and_centroid_differ_for_an_asymmetric_molecule():
    conf_set = _conformers("CCCCCCBr")
    com, _ = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions(center=CenterMode.CENTRE_OF_MASS)
    )
    centroid, _ = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions(center=CenterMode.CENTROID)
    )
    # The bromine's mass drags the centre of mass away from the geometric mean.
    assert com != centroid


def test_annular_shells_partition_atoms_that_cumulative_shells_nest():
    conf_set = _conformers(CHOLESTEROL)
    conf_id = conf_set.lowest.conf_id
    counts = RadialOptions(normalization=ShellNormalization.COUNT)

    _c, cumulative = compute_radial_shells(conf_set.mol_3d, conf_id, counts)
    _c, annular = compute_radial_shells(
        conf_set.mol_3d,
        conf_id,
        RadialOptions(normalization=ShellNormalization.COUNT, cumulative=False),
    )

    # Cumulative counts nest; annular ones are disjoint and sum to the same total.
    assert cumulative["r6_sp3C_n"] >= cumulative["r3_sp3C_n"]
    assert annular["r3_sp3C_n"] + annular["r6_sp3C_n"] == cumulative["r6_sp3C_n"]


def test_hydrogens_are_excluded_unless_requested():
    conf_set = _conformers("CCCCO")
    conf_id = conf_set.lowest.conf_id
    counts = RadialOptions(normalization=ShellNormalization.COUNT, shells=(10.0,))

    _c, heavy = compute_radial_shells(conf_set.mol_3d, conf_id, counts)
    _c, with_h = compute_radial_shells(
        conf_set.mol_3d,
        conf_id,
        RadialOptions(
            normalization=ShellNormalization.COUNT, shells=(10.0,), include_hydrogens=True
        ),
    )
    # Hydrogens are never sp3 carbons or electronegative, so class counts are
    # unchanged; what changes is the per-atom denominator, tested separately.
    assert heavy["r10_sp3C_n"] == with_h["r10_sp3C_n"]

    per_atom = RadialOptions(normalization=ShellNormalization.PER_ATOM, shells=(10.0,))
    _c, heavy_frac = compute_radial_shells(conf_set.mol_3d, conf_id, per_atom)
    _c, h_frac = compute_radial_shells(
        conf_set.mol_3d,
        conf_id,
        RadialOptions(
            normalization=ShellNormalization.PER_ATOM, shells=(10.0,), include_hydrogens=True
        ),
    )
    assert h_frac["r10_sp3C_A"] < heavy_frac["r10_sp3C_A"]


def test_empty_shell_yields_zero_not_nan():
    # A 0.1 A shell around a large molecule contains nothing to divide by.
    conf_set = _conformers(CHOLESTEROL)
    _c, values = compute_radial_shells(
        conf_set.mol_3d, conf_set.lowest.conf_id, RadialOptions(shells=(0.1,))
    )
    assert values["r0.1_sp3C_C"] == 0.0


# --- Whole-molecule shape descriptors -------------------------------------


def test_benzene_is_classified_flat_and_disc_like():
    conf_set = _conformers(BENZENE, n_confs=1)
    shape = compute_shape_descriptor_set(conf_set)

    assert shape.is_flat  # PBF near zero for a planar ring
    assert shape.shape_class == "disc"
    assert 0.0 <= shape.npr1 <= 1.0
    assert 0.0 <= shape.npr2 <= 1.0


def test_steroid_is_neither_flat_nor_disc_like():
    shape = compute_shape_descriptor_set(_conformers(CHOLESTEROL))

    assert not shape.is_flat  # a fused saturated ring system is substantially 3D
    assert shape.shape_class == "rod"
    assert shape.radius_of_gyration > 3.0
    assert shape.asphericity > 0.0


def test_shape_set_records_the_protocol_that_produced_the_geometry():
    conf_options = _conf_options(n_confs=3)
    conf_set = generate_conformer_set(Chem.MolFromSmiles(CAFFEINE), conf_options)
    shape = compute_shape_descriptor_set(conf_set)

    # Without this the numbers are not comparable across datasets.
    assert shape.conformer_options == conf_options
    assert shape.n_conformers == conf_set.n_conformers
    assert shape.conf_id == conf_set.lowest.conf_id


def test_mean_over_conformers_reports_no_single_conformer():
    conf_set = _conformers(CHOLESTEROL)
    shape = compute_shape_descriptor_set(conf_set, RadialOptions(conformer=ConformerChoice.MEAN))
    assert shape.conf_id is None
    assert set(shape.radial) == set(RadialOptions().keys())


def test_empty_conformer_set_is_rejected():
    conf_set = _conformers(BENZENE, n_confs=1)
    conf_set.conformers = []
    with pytest.raises(ValueError):
        compute_shape_descriptor_set(conf_set)


# --- Conformer sensitivity (the reproducibility hook) ---------------------


def test_sensitivity_is_zero_for_a_rigid_molecule():
    # Benzene has exactly one shape, so its descriptors cannot move.
    spread = radial_sensitivity(_conformers(BENZENE, n_confs=3))
    assert all(value == 0.0 for value in spread.values())


def test_sensitivity_covers_every_key_and_is_never_negative():
    spread = radial_sensitivity(_conformers("OCCCCCCO"))
    assert set(spread) == set(RadialOptions().keys())
    assert all(value >= 0.0 for value in spread.values())


def test_single_conformer_has_no_spread_to_report():
    spread = radial_sensitivity(_conformers(BENZENE, n_confs=1))
    assert all(value == 0.0 for value in spread.values())


# --- The record-level service ---------------------------------------------


def test_records_without_conformers_fail_cleanly():
    records = [_record(BENZENE, "benzene")]
    report = compute_shape_descriptors(records)

    assert report.computed == 0
    assert report.n_failed == 1
    assert "no conformers" in report.failures[0]
    assert records[0].shape3d is None  # the record is left usable


def test_generate_missing_produces_geometry_on_demand():
    records = [_record(BENZENE, "benzene")]
    report = compute_shape_descriptors(records, generate_missing=_conf_options(n_confs=2))

    assert report.computed == 1
    assert report.conformers_generated == 1
    assert records[0].shape3d is not None
    assert records[0].conformers is not None


def test_caches_in_place_and_reuses():
    records = [_record(CAFFEINE, "caffeine")]
    compute_shape_descriptors(records, generate_missing=_conf_options(n_confs=2))

    again = compute_shape_descriptors(records)
    assert again.computed == 0
    assert again.reused == 1
    assert again.records[0] is records[0]

    forced = compute_shape_descriptors(records, recompute=True)
    assert forced.computed == 1
    assert forced.reused == 0


def test_one_bad_molecule_does_not_abort_the_run():
    good = _record(BENZENE, "benzene")
    bad = _record(CAFFEINE, "no-geometry")
    good.conformers = _conformers(BENZENE, n_confs=1)

    report = compute_shape_descriptors([good, bad])
    assert report.computed == 1
    assert report.n_failed == 1
    assert good.shape3d is not None


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record(BENZENE, f"m{i}") for i in range(3)]
    compute_shape_descriptors(records, progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (3, 3)
