"""Chemical-space projection.

A dataset of fingerprints lives in a space of thousands of dimensions (one per
bit). *Chemical space visualization* squashes that down to two dimensions you can
actually look at, so clusters, outliers and diversity become visible at a glance.

Pipeline:

1. **Ensure fingerprints** — every molecule is encoded with one consistent
   fingerprint (reusing :mod:`wawekit.services.chemistry.fingerprints`; molecules
   that cannot be encoded are skipped).
2. **Build a matrix** — stack the bit vectors into an ``(n_molecules, n_bits)``
   array.
3. **Reduce to 2D** — with **PCA** (linear, fast, deterministic, and it reports
   how much variance each axis captures) or **t-SNE** (non-linear, better at
   revealing tight clusters, at the cost of speed and axis interpretability).

Why the options and result live here, not in ``models``
-------------------------------------------------------
Unlike descriptors or fingerprints, a projection is **not** a property of a
single molecule — a point's ``(x, y)`` depends on the *whole dataset* and the
method, and changes completely if the dataset does (much like a similarity score
depends on its query). So nothing in ``models`` refers to it, and by the rule
established in Module 4 — "a model may not depend upward", not "options live in
services" — the whole vocabulary sits in this service module. The result is held
by the GUI panel, never cached on the record, so stale coordinates cannot
survive a dataset change.

``scikit-learn`` is imported lazily inside :func:`project` so it does not slow
application startup — it is only paid for when a projection is actually run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from rdkit.DataStructs import ConvertToNumpyArray

from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.fingerprints import compute_fingerprints
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)

#: A projection needs at least this many valid points to be meaningful.
_MIN_POINTS = 3


class ProjectionMethod(StrEnum):
    """How to reduce the fingerprint matrix to two dimensions.

    A :class:`~enum.StrEnum` for the usual reason: it serialises straight into a
    settings file (Module 15) or a batch config (Module 13).

    Attributes
    ----------
    PCA:
        Principal Component Analysis — linear, fast, deterministic; the axes are
        interpretable (they report captured variance).
    TSNE:
        t-distributed Stochastic Neighbour Embedding — non-linear, emphasises
        local structure so clusters separate clearly, but slower and the axes
        carry no global meaning.

    """

    PCA = "PCA"
    TSNE = "t-SNE"

    @property
    def label(self) -> str:
        """Human-readable name for menus and dialogs."""
        return "PCA (linear, fast)" if self == ProjectionMethod.PCA else "t-SNE (clusters)"


@dataclass(frozen=True, slots=True)
class SpaceOptions:
    """Parameters for a chemical-space projection.

    Attributes
    ----------
    method:
        Which dimensionality reduction to apply.
    fingerprint:
        How to encode molecules before reducing. All molecules are encoded the
        same way, so the space is internally consistent.
    perplexity:
        t-SNE only: roughly how many neighbours each point balances against.
        Clamped to the dataset size at run time.
    random_seed:
        Seed so a projection is reproducible.

    """

    method: ProjectionMethod = ProjectionMethod.PCA
    fingerprint: FingerprintOptions = field(default_factory=FingerprintOptions)
    perplexity: float = 30.0
    random_seed: int = 0

    @property
    def label(self) -> str:
        """Compact one-line description for status messages and the panel."""
        base = f"{self.method} · {self.fingerprint.label}"
        return (
            f"{base} · perplexity {self.perplexity:g}"
            if self.method == ProjectionMethod.TSNE
            else base
        )


@dataclass(slots=True)
class ProjectionPoint:
    """One molecule placed in 2D space."""

    record: MoleculeRecord
    x: float
    y: float


@dataclass(slots=True)
class ProjectionResult:
    """The outcome of a projection: 2D points plus provenance.

    Attributes
    ----------
    method:
        The reduction that produced the coordinates.
    options:
        The full parameters the run used.
    points:
        One :class:`ProjectionPoint` per successfully projected molecule.
    skipped:
        ``"name: reason"`` for molecules left out (no usable fingerprint).
    explained_variance:
        For PCA, the fraction of variance captured by the two axes; ``None`` for
        t-SNE, whose axes have no such meaning.

    """

    method: ProjectionMethod
    options: SpaceOptions
    points: list[ProjectionPoint] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    explained_variance: tuple[float, float] | None = None

    @property
    def n_points(self) -> int:
        """Number of molecules placed in the space."""
        return len(self.points)

    @property
    def n_skipped(self) -> int:
        """Number of molecules that could not be projected."""
        return len(self.skipped)


def project(
    records: list[MoleculeRecord],
    options: SpaceOptions,
    progress: ProgressCallback | None = None,
) -> ProjectionResult:
    """Project ``records`` into a 2D chemical space.

    Parameters
    ----------
    records:
        Dataset to project. Fingerprints are computed/cached on them as needed;
        no other field is touched, and coordinates are *not* stored on records.
    options:
        Method and fingerprint parameters.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    ProjectionResult
        The 2D points and provenance.

    Raises
    ------
    ValueError
        If fewer than three molecules have a usable fingerprint — too few to form
        a meaningful space.

    """
    from sklearn.decomposition import PCA
    from sklearn.manifold import TSNE

    target_fp = options.fingerprint.normalized()
    # Encode everything the same way first; this reports progress for the phase
    # the user waits on most (t-SNE reduction itself is a single blocking step).
    compute_fingerprints(records, target_fp, progress=progress)

    result = ProjectionResult(method=options.method, options=options)
    valid: list[MoleculeRecord] = []
    rows: list[np.ndarray] = []
    for record in records:
        fp = record.fingerprint
        if fp is None or fp.options != target_fp:
            result.skipped.append(f"{record.name}: no {target_fp.label} fingerprint")
            continue
        arr = np.zeros((fp.n_bits,), dtype=np.uint8)
        ConvertToNumpyArray(fp.bits, arr)
        rows.append(arr)
        valid.append(record)

    if len(valid) < _MIN_POINTS:
        raise ValueError(
            f"Chemical space needs at least {_MIN_POINTS} molecules with a "
            f"{target_fp.label} fingerprint (only {len(valid)} available)."
        )

    matrix = np.vstack(rows).astype(np.float64)
    logger.info("Projecting %d molecule(s) with %s", len(valid), options.label)

    if options.method == ProjectionMethod.PCA:
        reducer = PCA(n_components=2, random_state=options.random_seed)
        coords = reducer.fit_transform(matrix)
        ev = reducer.explained_variance_ratio_
        result.explained_variance = (float(ev[0]), float(ev[1]))
    else:
        # t-SNE requires perplexity < n_samples; the /3 keeps it in the range
        # sklearn recommends and avoids its "perplexity too large" warning.
        perplexity = max(1.0, min(options.perplexity, (len(valid) - 1) / 3.0))
        reducer = TSNE(
            n_components=2,
            perplexity=perplexity,
            random_state=options.random_seed,
            init="pca",
        )
        coords = reducer.fit_transform(matrix)

    for record, (x, y) in zip(valid, coords, strict=True):
        result.points.append(ProjectionPoint(record=record, x=float(x), y=float(y)))

    if progress is not None:
        progress(len(records), len(records))
    logger.info("Projection complete: %d point(s), %d skipped", result.n_points, result.n_skipped)
    return result
