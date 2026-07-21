"""Tests for chemical-space projection (pure sklearn/RDKit, no Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.models.fingerprints import FingerprintKind, FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.chemical_space import (
    ProjectionMethod,
    SpaceOptions,
    project,
)

# A spread of structures so a projection is well-defined.
_SMILES = [
    "c1ccccc1",
    "Cc1ccccc1",
    "Oc1ccccc1",
    "Nc1ccccc1",
    "CCCCCC",
    "CCCCCCCC",
    "CCO",
    "CCCCO",
    "CC(=O)O",
    "CC(=O)Oc1ccccc1C(=O)O",
]


def _records() -> list[MoleculeRecord]:
    return [
        MoleculeRecord(mol=Chem.MolFromSmiles(smi), name=f"m{i}") for i, smi in enumerate(_SMILES)
    ]


def test_pca_projection_places_every_molecule():
    records = _records()
    result = project(records, SpaceOptions(method=ProjectionMethod.PCA, random_seed=0))

    assert result.n_points == len(records)
    assert result.n_skipped == 0
    # PCA reports how much variance the two axes capture.
    assert result.explained_variance is not None
    assert 0.0 <= sum(result.explained_variance) <= 1.0 + 1e-9
    # Every point carries real 2D coordinates and its backing record.
    for point in result.points:
        assert isinstance(point.x, float) and isinstance(point.y, float)
        assert point.record in records


def test_projection_computes_fingerprints_on_demand():
    records = _records()
    assert all(r.fingerprint is None for r in records)
    project(records, SpaceOptions(method=ProjectionMethod.PCA))
    # The projection encoded them as a side effect (cached in place).
    assert all(r.fingerprint is not None for r in records)


def test_tsne_projection_runs():
    records = _records()
    result = project(
        records, SpaceOptions(method=ProjectionMethod.TSNE, perplexity=5.0, random_seed=0)
    )
    assert result.n_points == len(records)
    # t-SNE axes carry no variance interpretation.
    assert result.explained_variance is None


def test_pca_is_deterministic_for_a_fixed_seed():
    a = project(_records(), SpaceOptions(method=ProjectionMethod.PCA, random_seed=42))
    b = project(_records(), SpaceOptions(method=ProjectionMethod.PCA, random_seed=42))
    ax = [round(p.x, 6) for p in a.points]
    bx = [round(p.x, 6) for p in b.points]
    assert ax == bx


def test_too_few_molecules_raises():
    records = [MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="only")]
    with pytest.raises(ValueError, match="at least"):
        project(records, SpaceOptions())


def test_specified_fingerprint_is_used():
    records = _records()
    maccs = FingerprintOptions(kind=FingerprintKind.MACCS)
    result = project(records, SpaceOptions(fingerprint=maccs))
    assert result.n_points == len(records)
    assert records[0].fingerprint.options == maccs.normalized()


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    project(_records(), SpaceOptions(), progress=lambda d, t: calls.append((d, t)))
    assert calls[-1][0] == calls[-1][1]  # ends at 100%
