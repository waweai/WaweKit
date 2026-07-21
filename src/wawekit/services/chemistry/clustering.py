"""Molecular clustering.

Partitions a dataset into groups of structurally similar molecules, by two
complementary methods:

* **Butina** — the cheminformatics standard. It works on Tanimoto *distance*
  (``1 - similarity``): pick the molecule with the most neighbours within a
  cutoff as a cluster centroid, remove it and its neighbours, repeat. No ``K`` to
  choose; the cluster count falls out of the cutoff, and dissimilar molecules end
  up as their own singleton clusters. Deterministic.
* **K-Means** — partitions the bit matrix into a fixed ``K`` clusters
  (scikit-learn). Needs ``K`` up front and is centroid-based on Euclidean
  distance.

Clusters are numbered **largest-first**, so cluster 0 is always the biggest
group — a stable convention the table sort and the scatter colouring both rely on.

Design rules (the shared seam):

* **A report, not just results** — counts and skipped molecules as data.
* **Ensure fingerprints first** — reusing Module 6, exactly as chemical space
  does; molecules that cannot be encoded are skipped, not clustered wrongly.
* **Cache in place, clear staleness** — assignments attach to the record (so the
  table column and the scatter colouring can read them), and molecules that fall
  out of a fresh run have their old assignment cleared, never left stale.

``scikit-learn`` is imported lazily inside :func:`cluster_molecules` so it costs
nothing until a K-Means run actually needs it.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from rdkit import DataStructs
from rdkit.DataStructs import ConvertToNumpyArray
from rdkit.ML.Cluster import Butina

from wawekit.models.clustering import ClusterAssignment, ClusterMethod, ClusterRun
from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.fingerprints import compute_fingerprints
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)

#: Clustering needs at least this many encodable molecules to be meaningful.
_MIN_MOLECULES = 2


@dataclass(frozen=True, slots=True)
class ClusterOptions:
    """Parameters for a clustering run.

    Attributes
    ----------
    method:
        Which algorithm to use.
    fingerprint:
        How to encode molecules before clustering (all encoded the same way).
    cutoff:
        Butina only: Tanimoto *distance* threshold (0–1). Molecules closer than
        this join a cluster. Lower → tighter, more numerous clusters.
    n_clusters:
        K-Means only: how many clusters to form (clamped to the dataset size).
    random_seed:
        K-Means only: seed for reproducibility.

    """

    method: ClusterMethod = ClusterMethod.BUTINA
    fingerprint: FingerprintOptions = field(default_factory=FingerprintOptions)
    cutoff: float = 0.35
    n_clusters: int = 5
    random_seed: int = 0

    @property
    def label(self) -> str:
        """Compact one-line description for status messages and tooltips."""
        param = (
            f"cutoff {self.cutoff:g}"
            if self.method == ClusterMethod.BUTINA
            else f"K={self.n_clusters}"
        )
        return f"{self.method} · {param} · {self.fingerprint.label}"


@dataclass(slots=True)
class ClusterReport:
    """Outcome of a clustering run.

    Attributes
    ----------
    records:
        The records the run covered (assignments cached on them in place).
    run:
        The :class:`ClusterRun` produced, or ``None`` if nothing was clustered.
    clustered:
        How many molecules were placed into a cluster.
    largest_cluster_size:
        Size of the biggest cluster (0 if none).
    skipped:
        ``"name: reason"`` for molecules left out (no usable fingerprint).

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    run: ClusterRun | None = None
    clustered: int = 0
    largest_cluster_size: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def n_clusters(self) -> int:
        """Number of clusters produced."""
        return self.run.n_clusters if self.run is not None else 0

    @property
    def n_skipped(self) -> int:
        """Number of molecules that could not be clustered."""
        return len(self.skipped)


def _butina_labels(valid: list[MoleculeRecord], cutoff: float) -> list[int]:
    """Return a cluster id per molecule using Butina, numbered largest-first."""
    fps = [record.fingerprint.bits for record in valid]
    # Condensed lower-triangle distance list, as Butina.ClusterData expects.
    distances: list[float] = []
    for i in range(1, len(fps)):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        distances.extend(1.0 - s for s in sims)

    clusters = Butina.ClusterData(distances, len(fps), cutoff, isDistData=True)
    clusters = sorted(clusters, key=len, reverse=True)  # largest cluster first

    labels = [0] * len(valid)
    for cluster_id, members in enumerate(clusters):
        for index in members:
            labels[index] = cluster_id
    return labels


def _kmeans_labels(valid: list[MoleculeRecord], k: int, seed: int) -> list[int]:
    """Return a cluster id per molecule using K-Means, numbered largest-first."""
    from sklearn.cluster import KMeans

    rows = []
    for record in valid:
        arr = np.zeros((record.fingerprint.n_bits,), dtype=np.uint8)
        ConvertToNumpyArray(record.fingerprint.bits, arr)
        rows.append(arr)
    matrix = np.vstack(rows).astype(np.float64)

    k = max(1, min(k, len(valid)))
    raw = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(matrix)

    # KMeans labels are arbitrary; renumber so cluster 0 is the largest.
    order = {old: new for new, (old, _count) in enumerate(Counter(raw).most_common())}
    return [order[label] for label in raw]


def cluster_molecules(
    records: list[MoleculeRecord],
    options: ClusterOptions,
    progress: ProgressCallback | None = None,
) -> ClusterReport:
    """Cluster ``records`` and cache a :class:`ClusterAssignment` on each.

    Parameters
    ----------
    records:
        Dataset to cluster. Fingerprints are computed/cached as needed; each
        record's ``cluster`` field is set (or cleared, if it cannot be encoded).
    options:
        Algorithm and fingerprint parameters.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    ClusterReport
        Counts, the run, and any skipped molecules.

    Raises
    ------
    ValueError
        If fewer than two molecules have a usable fingerprint.

    """
    target_fp = options.fingerprint.normalized()
    compute_fingerprints(records, target_fp, progress=progress)

    report = ClusterReport(records=list(records))
    valid: list[MoleculeRecord] = []
    for record in records:
        fp = record.fingerprint
        if fp is None or fp.options != target_fp:
            report.skipped.append(f"{record.name}: no {target_fp.label} fingerprint")
            record.cluster = None  # clear any stale assignment from a prior run
            continue
        valid.append(record)

    if len(valid) < _MIN_MOLECULES:
        raise ValueError(
            f"Clustering needs at least {_MIN_MOLECULES} molecules with a "
            f"{target_fp.label} fingerprint (only {len(valid)} available)."
        )

    logger.info("Clustering %d molecule(s): %s", len(valid), options.label)
    if options.method == ClusterMethod.BUTINA:
        labels = _butina_labels(valid, options.cutoff)
    else:
        labels = _kmeans_labels(valid, options.n_clusters, options.random_seed)

    sizes = Counter(labels)
    n_clusters = len(sizes)
    run = ClusterRun(method=options.method, n_clusters=n_clusters, label=options.label)
    for record, cluster_id in zip(valid, labels, strict=True):
        record.cluster = ClusterAssignment(
            cluster_id=cluster_id, cluster_size=sizes[cluster_id], run=run
        )

    report.run = run
    report.clustered = len(valid)
    report.largest_cluster_size = max(sizes.values())
    if progress is not None:
        progress(len(records), len(records))
    logger.info(
        "Clustering complete: %d cluster(s), largest %d, %d skipped",
        n_clusters,
        report.largest_cluster_size,
        report.n_skipped,
    )
    return report
