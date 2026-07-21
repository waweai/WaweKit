"""Similarity search: rank a dataset against one query molecule.

This is what Module 6's bit vectors were built for. The chemistry is one line
(``BulkTanimotoSimilarity``); everything else in this file exists to make sure
that line is asked a question worth answering.

Bulk, not a Python loop
-----------------------
RDKit exposes both ``TanimotoSimilarity(a, b)`` and
``BulkTanimotoSimilarity(a, [b, c, d, ...])``. They compute the same numbers,
but the bulk form crosses the Python↔C++ boundary **once** for the whole
dataset instead of once per molecule, and loops in C++. On a real library that
is the difference between instant and sluggish, and it costs nothing to prefer
— which is why Module 6 kept RDKit's native ``ExplicitBitVect`` instead of
converting to numpy: bulk consumes it directly.

Comparability is enforced, not assumed
--------------------------------------
RDKit guards exactly one thing here: **length**. Score a 2048-bit Morgan vector
against a 167-bit MACCS one and it raises ``BitVects must be same length`` —
loud, obvious, safe. It has nothing at all to say about two vectors that are the
same length and mean different things (all measured, aspirin vs salicylic acid)::

    Morgan r2 vs Morgan r2   0.448   <- the truth
    Morgan r2 vs Morgan r3   0.394   <- silent, plausible, wrong
    Morgan r2 vs RDKit path  0.005   <- silent; a real hit now looks like noise
    ECFP     vs FCFP         0.000   <- silent; a close analogue scores zero

The dangerous mistake is the quiet one. Every number above is a float in the
range a chemist expects, and only the first means anything. So this service does
two things before scoring:

1. **Encodes the query with the same options as the dataset**, by running the
   fingerprint service over the records first (cheap — it reuses any matching
   vectors already cached) and building the query's vector with those same
   options.
2. **Checks every record with**
   :meth:`~wawekit.models.fingerprints.Fingerprint.is_comparable_to` anyway,
   and refuses to score the ones that fail.

Step 2 looks redundant after step 1. It isn't, and the reason is worth knowing:
the fingerprint service overwrites a record's vector only when computation
*succeeds*. When RDKit throws on a molecule, that record quietly keeps whatever
fingerprint it had before. Re-encode a MACCS dataset as Morgan with one failure
in it and exactly one record is still MACCS — same field, same type, different
meaning. Step 2 costs one equality check per record and is the only thing
standing between that record and a plausible, meaningless score in a hit list
someone orders compounds from.

Design rules (the same seam as every service since Module 2):

* **Qt-free** — a plain ``progress`` callback.
* **A report, not just results** — what was scored, what was skipped, and why.
* **One bad molecule never aborts the run.**
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem, DataStructs

from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.similarity import SimilarityMetric, SimilarityQuery, SimilarityScore
from wawekit.services.chemistry.fingerprints import compute_fingerprint, compute_fingerprints
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)

#: Metric → RDKit's bulk implementation. Keyed by the enum members, which is
#: safe to look up with a plain string too: ``StrEnum`` hashes by its *value*,
#: so ``_BULK_FUNCTIONS["Tanimoto"]`` resolves exactly like
#: ``_BULK_FUNCTIONS[SimilarityMetric.TANIMOTO]``. That matters because a metric
#: can arrive from a Qt ``QVariant`` or a Module 15 settings file as a bare str.
_BULK_FUNCTIONS = {
    SimilarityMetric.TANIMOTO: DataStructs.BulkTanimotoSimilarity,
    SimilarityMetric.DICE: DataStructs.BulkDiceSimilarity,
    SimilarityMetric.COSINE: DataStructs.BulkCosineSimilarity,
}


@dataclass(frozen=True, slots=True)
class SimilarityRequest:
    """Everything needed to run one search.

    Lives in the service rather than in ``models`` for the reason Module 4
    established with ``StandardizationOptions``: nothing in ``models`` refers to
    it, so it does not need to be there. (Contrast
    :class:`~wawekit.models.similarity.SimilarityQuery`, which *is* a model —
    every :class:`~wawekit.models.similarity.SimilarityScore` holds one.)

    Attributes
    ----------
    query_mol:
        The molecule to search *for*. May be a molecule from the dataset or one
        parsed from pasted SMILES that appears nowhere in it.
    query_name:
        Display name for the query.
    metric:
        Which similarity coefficient to use.
    fingerprint:
        How to encode both the query and the dataset. Both sides always use
        these same options — that is what makes the scores mean anything.

    """

    query_mol: Chem.Mol
    query_name: str
    metric: SimilarityMetric = SimilarityMetric.TANIMOTO
    fingerprint: FingerprintOptions = field(default_factory=FingerprintOptions)


@dataclass(slots=True)
class SimilarityReport:
    """Outcome of a similarity search.

    Attributes
    ----------
    query:
        The query the scores are against (metric and fingerprint options
        included) — the same object every produced
        :class:`~wawekit.models.similarity.SimilarityScore` points at.
    ranked:
        Every scored record, best match first. This is the hit list.
    skipped:
        ``"name: reason"`` per record that could not be scored — almost always
        a molecule whose fingerprint RDKit could not build.
    fingerprints_computed:
        How many dataset fingerprints this run had to calculate (0 when the
        dataset was already encoded with these options).

    """

    query: SimilarityQuery
    ranked: list[MoleculeRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    fingerprints_computed: int = 0

    @property
    def n_scored(self) -> int:
        """How many records received a score."""
        return len(self.ranked)

    @property
    def n_skipped(self) -> int:
        """How many records could not be scored."""
        return len(self.skipped)

    def top(self, n: int = 5) -> list[MoleculeRecord]:
        """Return the ``n`` best matches (the hit list's head)."""
        return self.ranked[:n]


def search_similar(
    records: list[MoleculeRecord],
    request: SimilarityRequest,
    progress: ProgressCallback | None = None,
) -> SimilarityReport:
    """Score every record against ``request.query_mol`` and rank them.

    Each record's ``similarity`` field is filled in place with a
    :class:`~wawekit.models.similarity.SimilarityScore`, or set to ``None`` if
    it could not be scored. Setting it to ``None`` rather than leaving the old
    value is deliberate: a stale score from a previous query, sitting in a
    column headed by a *new* query, is worse than a blank cell.

    Parameters
    ----------
    records:
        The dataset to search. Fingerprints are computed and cached on these as
        needed.
    request:
        Query molecule, metric and fingerprint options.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).
        Reports the fingerprint phase, which is where essentially all the time
        goes — the scoring itself is a single C++ call.

    Returns
    -------
    SimilarityReport
        The ranked hit list plus what was skipped.

    """
    options = request.fingerprint.normalized()
    metric = SimilarityMetric(request.metric)

    # Encode the dataset first. This reuses vectors already cached with these
    # exact options and recomputes any that were built differently, so by the
    # time we score, the whole dataset is on one scale.
    fp_report = compute_fingerprints(records, options, progress=progress)

    # The query is encoded with those same options — never with defaults.
    query_fp = compute_fingerprint(request.query_mol, options)
    query = SimilarityQuery(
        smiles=Chem.MolToSmiles(request.query_mol),
        name=request.query_name,
        metric=metric,
        fingerprint=options,
    )
    report = SimilarityReport(query=query, fingerprints_computed=fp_report.computed)

    logger.info(
        "Similarity search: %s over %d record(s)",
        query.label,
        len(records),
    )

    # Partition before scoring: bulk needs a dense list of vectors, and we must
    # remember which record each position came from.
    scorable: list[MoleculeRecord] = []
    for record in records:
        fingerprint = record.fingerprint
        if fingerprint is None:
            record.similarity = None
            report.skipped.append(f"{record.name}: no fingerprint could be computed")
        elif not fingerprint.is_comparable_to(query_fp):
            # Reachable, and this is how. compute_fingerprints assigns a new
            # vector only on success; when RDKit throws for a molecule, the
            # record silently *keeps the fingerprint it already had*. So a
            # dataset encoded as MACCS, re-encoded as Morgan with one failure,
            # ends up here holding a MACCS vector while everything else is
            # Morgan. Without this check RDKit would happily score it against
            # the Morgan query and return a plausible, meaningless number.
            record.similarity = None
            report.skipped.append(
                f"{record.name}: fingerprint is {fingerprint.options.label}, "
                f"not comparable with {options.label}"
            )
        else:
            scorable.append(record)

    if scorable:
        # One crossing into C++ for the entire dataset.
        scores = _BULK_FUNCTIONS[metric](query_fp.bits, [r.fingerprint.bits for r in scorable])
        for record, value in zip(scorable, scores, strict=True):
            record.similarity = SimilarityScore(value=float(value), query=query)
        # Best first — the hit list is the whole point, so ranking is the
        # service's job, not something each caller re-derives.
        report.ranked = sorted(scorable, key=lambda r: r.similarity.value, reverse=True)

    logger.info(
        "Similarity search complete: %d scored, %d skipped, best=%s",
        report.n_scored,
        report.n_skipped,
        f"{report.ranked[0].similarity.value:.3f}" if report.ranked else "n/a",
    )
    return report
