"""Dataset-level reproducibility metrics, computed from a :class:`DivergenceRun`.

Three numbers a paper (or a curation QA check) actually wants:

1. **Reproducibility score** — the fraction of molecules on which *every*
   protocol agrees. One honest headline number per identity convention.
2. **Pairwise agreement matrix** — for every *pair* of protocols, what fraction
   of molecules do they individually agree on? This is finer-grained than the
   all-agree score: two "similar" protocols (e.g. ChEMBL-like and Aggressive,
   which differ only by three operations) should agree far more often than two
   very different ones (Minimal and Aggressive).
3. **Cause spectrum** — of the labile molecules, how often is each operation
   implicated? This is the taxonomy: "62% of divergence is tautomer-driven, 30%
   is salt-handling, ...".

Kept Qt-free and matplotlib-free — this module only computes numbers. Rendering
(a heatmap, a bar chart) is the GUI panel's job (R4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from wawekit.services.reproducibility.divergence import DivergenceRun
from wawekit.services.reproducibility.protocol import StandardOp


@dataclass(frozen=True, slots=True)
class ProtocolPairAgreement:
    """Agreement between one pair of protocols, on both identity conventions."""

    protocol_a: str
    protocol_b: str
    smiles_agreement: float
    inchikey_agreement: float


@dataclass(slots=True)
class ReproducibilityMetrics:
    """Dataset-level summary of a :class:`DivergenceRun`.

    Attributes
    ----------
    n_molecules:
        Molecules analyzed.
    smiles_reproducibility:
        Fraction of molecules where *every* protocol produced the same
        canonical SMILES (1.0 = perfectly reproducible under this identity).
    inchikey_reproducibility:
        Same, for InChIKey identity.
    n_labile:
        Molecules where at least one identity convention disagrees — the exact
        count from the run (the union of SMILES-labile and InChIKey-labile,
        which can exceed either count alone).
    n_with_failures:
        Molecules where at least one protocol failed outright. Failures are
        not divergence — they are reported as their own number.
    pairwise:
        Agreement for every protocol pair, both identities.
    cause_spectrum:
        Fraction of *labile* molecules implicating each operation (sums to more
        than 1.0 in general, since one molecule can implicate several operations).

    """

    n_molecules: int = 0
    smiles_reproducibility: float = 1.0
    inchikey_reproducibility: float = 1.0
    n_labile: int = 0
    n_with_failures: int = 0
    pairwise: list[ProtocolPairAgreement] = field(default_factory=list)
    cause_spectrum: dict[StandardOp, float] = field(default_factory=dict)


def compute_metrics(run: DivergenceRun) -> ReproducibilityMetrics:
    """Compute dataset-level reproducibility metrics from a completed run.

    Parameters
    ----------
    run:
        A completed :func:`~wawekit.services.reproducibility.divergence.analyze_divergence` run.

    Returns
    -------
    ReproducibilityMetrics
        The headline score, the pairwise matrix, and the cause spectrum.

    """
    n = run.n_molecules
    if n == 0:
        return ReproducibilityMetrics()

    metrics = ReproducibilityMetrics(
        n_molecules=n,
        smiles_reproducibility=1.0 - (run.n_smiles_labile / n),
        inchikey_reproducibility=1.0 - (run.n_inchikey_labile / n),
        n_labile=run.n_labile,
        n_with_failures=run.n_with_failures,
    )

    # Pairwise agreement: for each pair of protocol indices, what fraction of
    # molecules share the same form between just those two protocols? Only
    # molecules where BOTH forms are valid count — two empty results from two
    # failed protocols match as strings but demonstrate nothing, so they must
    # not inflate the agreement score.
    protocol_names = [p.name for p in run.protocols]
    for i, j in combinations(range(len(run.protocols)), 2):
        smiles_matches = smiles_valid = inchikey_matches = inchikey_valid = 0
        for result in run.results:
            a, b = result.forms[i], result.forms[j]
            if a.error is None and b.error is None:
                smiles_valid += 1
                if a.smiles == b.smiles:
                    smiles_matches += 1
            if a.inchikey and b.inchikey:
                inchikey_valid += 1
                if a.inchikey == b.inchikey:
                    inchikey_matches += 1
        metrics.pairwise.append(
            ProtocolPairAgreement(
                protocol_a=protocol_names[i],
                protocol_b=protocol_names[j],
                smiles_agreement=smiles_matches / smiles_valid if smiles_valid else 1.0,
                inchikey_agreement=inchikey_matches / inchikey_valid if inchikey_valid else 1.0,
            )
        )

    labile = [r for r in run.results if r.is_labile]
    if labile:
        counts = dict.fromkeys(StandardOp, 0)
        for result in labile:
            for op in set(result.causes):
                counts[op] += 1
        metrics.cause_spectrum = {op: count / len(labile) for op, count in counts.items()}

    return metrics
