"""Tests for molecular clustering (RDKit Butina + sklearn K-Means, no Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.models.clustering import ClusterMethod
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.clustering import ClusterOptions, cluster_molecules

# Two tight families (aromatics and alkanes) plus a couple of oddities, so the
# clustering has something real to find.
_SMILES = [
    "c1ccccc1",
    "Cc1ccccc1",
    "Oc1ccccc1",
    "Nc1ccccc1",
    "CCCCCC",
    "CCCCCCC",
    "CCCCCCCC",
    "CCCCCCCCC",
    "CC(=O)Oc1ccccc1C(=O)O",
    "OCC1OC(O)C(O)C(O)C1O",
]


def _records() -> list[MoleculeRecord]:
    return [
        MoleculeRecord(mol=Chem.MolFromSmiles(smi), name=f"m{i}") for i, smi in enumerate(_SMILES)
    ]


def test_butina_assigns_every_molecule_a_cluster():
    records = _records()
    report = cluster_molecules(records, ClusterOptions(method=ClusterMethod.BUTINA, cutoff=0.4))

    assert report.clustered == len(records)
    assert report.n_skipped == 0
    assert report.n_clusters >= 1
    assert all(r.cluster is not None for r in records)
    # Every assignment carries the run that produced it.
    assert all(r.cluster.run is report.run for r in records)


def test_clusters_are_numbered_largest_first():
    records = _records()
    cluster_molecules(records, ClusterOptions(method=ClusterMethod.BUTINA, cutoff=0.4))
    sizes: dict[int, int] = {}
    for r in records:
        sizes[r.cluster.cluster_id] = sizes.get(r.cluster.cluster_id, 0) + 1
    # Cluster 0 is at least as large as cluster 1, etc.
    ordered = [sizes[k] for k in sorted(sizes)]
    assert ordered == sorted(ordered, reverse=True)


def test_lower_cutoff_makes_more_clusters():
    loose = cluster_molecules(_records(), ClusterOptions(cutoff=0.6))
    strict = cluster_molecules(_records(), ClusterOptions(cutoff=0.2))
    assert strict.n_clusters >= loose.n_clusters


def test_kmeans_produces_the_requested_cluster_count():
    records = _records()
    report = cluster_molecules(
        records, ClusterOptions(method=ClusterMethod.KMEANS, n_clusters=3, random_seed=0)
    )
    assert report.n_clusters == 3
    assert max(r.cluster.cluster_id for r in records) == 2


def test_kmeans_is_deterministic_for_a_fixed_seed():
    a = cluster_molecules(_records(), ClusterOptions(method=ClusterMethod.KMEANS, n_clusters=3))
    b = cluster_molecules(_records(), ClusterOptions(method=ClusterMethod.KMEANS, n_clusters=3))
    assert [r.cluster.cluster_id for r in a.records] == [r.cluster.cluster_id for r in b.records]


def test_clustering_computes_fingerprints_on_demand():
    records = _records()
    assert all(r.fingerprint is None for r in records)
    cluster_molecules(records, ClusterOptions())
    assert all(r.fingerprint is not None for r in records)


def test_too_few_molecules_raises():
    records = [MoleculeRecord(mol=Chem.MolFromSmiles("CCO"), name="only")]
    with pytest.raises(ValueError, match="at least"):
        cluster_molecules(records, ClusterOptions())


def test_recluster_overwrites_previous_assignment():
    records = _records()
    cluster_molecules(records, ClusterOptions(method=ClusterMethod.KMEANS, n_clusters=2))
    first_run = records[0].cluster.run
    cluster_molecules(records, ClusterOptions(method=ClusterMethod.KMEANS, n_clusters=4))
    # Every record now points at the new run, not the stale one.
    assert all(r.cluster.run is not first_run for r in records)
    assert records[0].cluster.run.n_clusters == 4


def test_progress_callback_reaches_total():
    calls: list[tuple[int, int]] = []
    cluster_molecules(_records(), ClusterOptions(), progress=lambda d, t: calls.append((d, t)))
    assert calls[-1][0] == calls[-1][1]
