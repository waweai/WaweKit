"""The clustering domain model.

*Clustering* partitions a dataset into groups of structurally similar molecules —
the "what families are in my library?" question, the natural companion to the
chemical-space map of Module 10.

A cluster id is relational, like a similarity score
---------------------------------------------------
A molecule's cluster id is not intrinsic to it: it depends on the *whole
dataset*, the algorithm and its parameters. Load different molecules and the same
structure lands in a different cluster. So — exactly as
:class:`~wawekit.models.similarity.SimilarityScore` refuses to be a bare float and
carries its :class:`~wawekit.models.similarity.SimilarityQuery` — a
:class:`ClusterAssignment` carries the :class:`ClusterRun` that produced it. The
id can then always be read with the context that makes it meaningful, and a stale
assignment from an earlier run is recognisable rather than trusted.

Why this lives in ``models``
----------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``cluster: ClusterAssignment | None`` field, and ``models`` may never import from
``services``. So the *data* (this module) is a model; the algorithm that fills it
lives in :mod:`wawekit.services.chemistry.clustering`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ClusterMethod(StrEnum):
    """How to partition the dataset.

    A :class:`~enum.StrEnum` so it serialises straight into settings (Module 15)
    or a batch config (Module 13).

    Attributes
    ----------
    BUTINA:
        Sphere-exclusion clustering on Tanimoto distance (the cheminformatics
        standard). Threshold-based — no ``K`` to choose; the cluster count falls
        out of the cutoff, and singletons are kept as their own clusters.
    KMEANS:
        k-means partitioning of the bit matrix into a fixed number of clusters.

    """

    BUTINA = "Butina"
    KMEANS = "K-Means"

    @property
    def label(self) -> str:
        """Human-readable name for menus and dialogs."""
        return (
            "Butina (similarity threshold)" if self == ClusterMethod.BUTINA else "K-Means (fixed K)"
        )


@dataclass(frozen=True, slots=True)
class ClusterRun:
    """Context shared by every assignment from one clustering run.

    Attributes
    ----------
    method:
        The algorithm used.
    n_clusters:
        How many clusters the run produced.
    label:
        Full human-readable description (method, parameters, fingerprint), shown
        in tooltips so an id can always be read with its provenance.

    """

    method: ClusterMethod
    n_clusters: int
    label: str


@dataclass(frozen=True, slots=True)
class ClusterAssignment:
    """One molecule's membership in a clustering run.

    Attributes
    ----------
    cluster_id:
        0-based cluster index. Clusters are numbered largest-first, so cluster 0
        is always the biggest group.
    cluster_size:
        How many molecules share this cluster.
    run:
        The :class:`ClusterRun` that produced this assignment.

    """

    cluster_id: int
    cluster_size: int
    run: ClusterRun

    @property
    def display(self) -> str:
        """Short cell text: the cluster id as a string."""
        return str(self.cluster_id)

    @property
    def tooltip(self) -> str:
        """Hover text: the run's provenance plus this cluster's size."""
        return f"{self.run.label}\nCluster {self.cluster_id} · {self.cluster_size} molecule(s)"
