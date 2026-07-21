"""Tests for conformer generation (pure RDKit, no Qt / no web view)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.models.conformers import ConformerOptions, ForceField
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.conformers import (
    generate_conformer_set,
    generate_conformers,
)

# A small, flexible molecule embeds fast and yields several distinct shapes.
FLEXIBLE = "OCCCCCCO"  # hexane-1,6-diol


def _record(smiles: str, name: str) -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return MoleculeRecord(mol=mol, name=name)


def _options(**changes) -> ConformerOptions:
    """Build options with small, reproducible defaults, overriding as needed."""
    params = {"n_confs": 8, "random_seed": 1}
    params.update(changes)
    return ConformerOptions(**params)


def test_generate_conformer_set_is_ranked_by_energy():
    conf_set = generate_conformer_set(Chem.MolFromSmiles(FLEXIBLE), _options())

    assert conf_set.n_conformers >= 1
    assert conf_set.force_field_used == ForceField.MMFF94
    energies = [c.energy for c in conf_set.conformers]
    assert all(e is not None for e in energies)
    assert energies == sorted(energies)  # lowest energy first
    # The lowest-energy conformer is the RMSD reference.
    assert conf_set.conformers[0].rms_to_lowest is None
    if conf_set.n_conformers > 1:
        assert all(c.rms_to_lowest >= 0 for c in conf_set.conformers[1:])


def test_none_force_field_leaves_energies_unset():
    conf_set = generate_conformer_set(
        Chem.MolFromSmiles("CCCCO"), _options(force_field=ForceField.NONE)
    )
    assert conf_set.force_field_used == ForceField.NONE
    assert all(c.energy is None for c in conf_set.conformers)


def test_mol_3d_has_hydrogens_and_is_separate_from_input():
    mol = Chem.MolFromSmiles("CCO")
    conf_set = generate_conformer_set(mol, _options(n_confs=3))
    # AddHs was applied to the 3D mol; the input record's mol is untouched.
    assert conf_set.mol_3d.GetNumAtoms() > mol.GetNumAtoms()
    assert conf_set.mol_3d.GetNumConformers() >= 1


def test_molblock_and_sdf_export():
    conf_set = generate_conformer_set(Chem.MolFromSmiles("CCCCO"), _options(n_confs=4))
    lowest = conf_set.lowest

    molblock = conf_set.molblock_for(lowest.conf_id)
    assert "V2000" in molblock  # an MDL mol block with 3D coords

    sdf = conf_set.to_sdf()
    assert sdf.count("$$$$") == conf_set.n_conformers  # one record per conformer


def test_energy_range_is_nonnegative_or_none():
    conf_set = generate_conformer_set(Chem.MolFromSmiles(FLEXIBLE), _options())
    rng = conf_set.energy_range
    assert rng is None or rng >= 0


def test_generate_conformers_caches_in_place_and_reuses():
    records = [_record("CCCCO", "butanol")]
    report = generate_conformers(records, _options(n_confs=3))
    assert report.computed == 1
    assert report.total_conformers >= 1
    assert records[0].conformers is not None
    assert records[0] is report.records[0]

    again = generate_conformers(records, _options(n_confs=3))
    assert again.computed == 0
    assert again.reused == 1


def test_recompute_regenerates():
    records = [_record("CCCCO", "butanol")]
    generate_conformers(records, _options(n_confs=3))
    report = generate_conformers(records, _options(n_confs=3), recompute=True)
    assert report.computed == 1
    assert report.reused == 0


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    records = [_record("CCO", f"m{i}") for i in range(3)]
    generate_conformers(records, _options(n_confs=2), progress=lambda d, t: calls.append((d, t)))
    assert calls[-1] == (3, 3)
