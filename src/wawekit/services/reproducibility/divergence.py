"""Divergence analysis: whether standardization agrees across protocols, and why not.

Given a molecule and a set of protocols (R1), this module answers two questions:

1. **Do they agree?** — on canonical-SMILES identity and on InChIKey identity
   separately, since R1 showed the two can disagree (InChI absorbs tautomer
   changes that SMILES reveals).
2. **If not, why?** — via **ablation**: starting from the most thorough protocol
   in the comparison, toggle each operation off one at a time and check whether
   doing so changes the result to match another protocol's output. The first
   operation whose removal resolves a disagreement is recorded as its likely
   cause. This is what turns "these disagree" into "these disagree *because of
   tautomer canonicalization*" — the taxonomy the paper is built on.

Qt-free, so a divergence run scales to a benchmark harness (R5) unattended.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem

from wawekit.services.reproducibility.protocol import (
    OPERATION_ORDER,
    StandardForm,
    StandardizationProtocol,
    StandardOp,
    standardize,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MoleculeDivergence:
    """The divergence result for one molecule across a set of protocols.

    Attributes
    ----------
    name:
        Molecule identifier (for reporting).
    forms:
        One :class:`~wawekit.services.reproducibility.protocol.StandardForm` per
        protocol, in the order the protocols were given.
    smiles_agree:
        Whether every protocol produced the same canonical SMILES.
    inchikey_agree:
        Whether every protocol produced the same InChIKey.
    causes:
        Operations implicated in the divergence, most-likely first (empty if
        both identities agree, or if ablation could not isolate a cause).

    """

    name: str
    forms: tuple[StandardForm, ...]
    smiles_agree: bool
    inchikey_agree: bool
    causes: tuple[StandardOp, ...] = field(default_factory=tuple)

    @property
    def is_labile(self) -> bool:
        """Whether *any* identity convention disagrees across protocols."""
        return not (self.smiles_agree and self.inchikey_agree)

    @property
    def n_failed(self) -> int:
        """Number of protocols that failed outright on this molecule."""
        return sum(1 for f in self.forms if f.error is not None)

    @property
    def all_failed(self) -> bool:
        """Whether every protocol failed — no identity was produced at all."""
        return bool(self.forms) and all(f.error is not None for f in self.forms)

    @property
    def n_distinct_smiles(self) -> int:
        """Number of distinct canonical-SMILES forms produced."""
        return len({f.smiles for f in self.forms if f.smiles})

    @property
    def n_distinct_inchikeys(self) -> int:
        """Number of distinct InChIKey forms produced."""
        return len({f.inchikey for f in self.forms if f.inchikey})


def _attribute_cause(mol: Chem.Mol, protocol: StandardizationProtocol) -> list[StandardOp]:
    """Find which operations, if removed from ``protocol``, change its result.

    Ablation: for each enabled operation (checked in reverse application order,
    since later operations are more likely to be the "last mover" on a
    disagreement), standardize with that one operation switched off and compare
    identities to the full protocol. An operation is implicated if removing it
    changes *either* identity — the same operation can affect both, one, or
    (rarely) neither if two operations jointly determine the outcome.

    Returns operations most-to-least likely to be the cause: those that change
    the InChIKey (the "deeper" identity) are ranked first.
    """
    full = standardize(mol, protocol)
    if not full.ok:
        return []  # can't attribute a cause when the full protocol itself failed

    smiles_movers: list[StandardOp] = []
    inchikey_movers: list[StandardOp] = []
    for op in reversed(protocol.applied_ops()):
        ablated = protocol.with_op(op, False)
        result = standardize(mol, ablated)
        if not result.ok:
            continue
        if result.inchikey != full.inchikey:
            inchikey_movers.append(op)
        elif result.smiles != full.smiles:
            smiles_movers.append(op)

    return inchikey_movers + smiles_movers


def _standardize_with(mol: Chem.Mol, standardizer: object) -> StandardForm:
    """Standardize with either a composed protocol or an external standardizer.

    Accepting both is what lets a single audit compare protocols we compose
    against production pipelines we do not control (see
    :mod:`.standardizers`). Duck-typed on ``standardize_mol`` rather than
    isinstance-checked, so the protocol path stays free of any import from the
    adapter module.
    """
    if hasattr(standardizer, "standardize_mol"):
        return standardizer.standardize_mol(mol)
    return standardize(mol, standardizer)


def _ablatable_protocols(standardizers: tuple[object, ...]) -> list[StandardizationProtocol]:
    """Return the composed protocols among ``standardizers``.

    Cause attribution needs operations it can switch off, which an opaque
    external pipeline does not provide.
    """
    protocols: list[StandardizationProtocol] = []
    for item in standardizers:
        if isinstance(item, StandardizationProtocol):
            protocols.append(item)
        elif getattr(item, "is_ablatable", False) and hasattr(item, "protocol"):
            protocols.append(item.protocol)
    return protocols


def analyze_molecule(
    mol: Chem.Mol,
    protocols: tuple[object, ...],
    name: str = "",
    attribute_causes: bool = True,
) -> MoleculeDivergence:
    """Standardize ``mol`` with every standardizer and analyze the divergence.

    Parameters
    ----------
    mol:
        The molecule to check.
    protocols:
        The standardizers to compare, in the order their forms are reported.
        Each may be a composed
        :class:`~wawekit.services.reproducibility.protocol.StandardizationProtocol`
        or any object satisfying
        :class:`~wawekit.services.reproducibility.standardizers.Standardizer`,
        so a comparison may mix composed protocols with production pipelines.
    name:
        Display name for reporting.
    attribute_causes:
        If ``True`` and the molecule is labile, run ablation to attribute a
        cause. Attribution requires at least one *ablatable* standardizer; a
        comparison consisting only of opaque external pipelines reports
        divergence without causes, which is a limit of what can be known rather
        than a failure to find one. Ablation costs one extra standardization
        per operation, so it can be disabled for a fast first pass.

    Returns
    -------
    MoleculeDivergence
        The per-standardizer forms and the agreement/cause analysis.

    """
    forms = tuple(_standardize_with(mol, p) for p in protocols)
    # Agreement is judged only across forms that produced a value: a protocol
    # *failing* is a failure (tracked via n_failed/all_failed), not evidence of
    # divergence — and a molecule every protocol failed on must not be counted
    # as "reproducible" just because the empty results happen to match.
    smiles_values = {f.smiles for f in forms if f.error is None}
    inchikey_values = {f.inchikey for f in forms if f.inchikey}
    smiles_agree = len(smiles_values) <= 1
    inchikey_agree = len(inchikey_values) <= 1

    causes: tuple[StandardOp, ...] = ()
    if attribute_causes and not (smiles_agree and inchikey_agree):
        ablatable = _ablatable_protocols(protocols)
        if ablatable:
            richest = max(ablatable, key=lambda p: len(p.operations))
            causes = tuple(_attribute_cause(mol, richest))

    return MoleculeDivergence(
        name=name,
        forms=forms,
        smiles_agree=smiles_agree,
        inchikey_agree=inchikey_agree,
        causes=causes,
    )


@dataclass(slots=True)
class DivergenceRun:
    """Outcome of a divergence analysis over a dataset.

    Attributes
    ----------
    protocols:
        The standardizers compared (composed protocols, external adapters, or
        a mix — see :func:`analyze_divergence`).
    results:
        One :class:`MoleculeDivergence` per input molecule.

    """

    protocols: tuple[object, ...] = ()
    results: list[MoleculeDivergence] = field(default_factory=list)

    @property
    def n_molecules(self) -> int:
        """Total molecules analyzed."""
        return len(self.results)

    @property
    def n_labile(self) -> int:
        """Molecules where at least one identity convention disagrees."""
        return sum(1 for r in self.results if r.is_labile)

    @property
    def n_smiles_labile(self) -> int:
        """Molecules where canonical-SMILES identity disagrees across protocols."""
        return sum(1 for r in self.results if not r.smiles_agree)

    @property
    def n_inchikey_labile(self) -> int:
        """Molecules where InChIKey identity disagrees across protocols."""
        return sum(1 for r in self.results if not r.inchikey_agree)

    @property
    def n_with_failures(self) -> int:
        """Molecules where at least one protocol failed outright.

        Failures are reported separately from lability: a failed protocol
        produced no identity, so it is evidence of fragility, not divergence.
        """
        return sum(1 for r in self.results if r.n_failed > 0)

    def cause_counts(self) -> dict[StandardOp, int]:
        """Return how many labile molecules implicate each operation.

        A molecule with multiple implicated operations counts once per
        operation; :func:`analyze_molecule` ranks likely-cause operations first
        within each result, but this tally is unordered across the dataset.
        """
        counts: dict[StandardOp, int] = dict.fromkeys(OPERATION_ORDER, 0)
        for result in self.results:
            for op in set(result.causes):
                counts[op] += 1
        return counts


def analyze_divergence(
    records: list[tuple[str, Chem.Mol]],
    protocols: tuple[object, ...],
    attribute_causes: bool = True,
    progress: object = None,
) -> DivergenceRun:
    """Run divergence analysis over a dataset.

    Parameters
    ----------
    records:
        ``(name, mol)`` pairs to analyze. Kept decoupled from
        :class:`~wawekit.models.molecule.MoleculeRecord` so this module has no
        dependency on the GUI-facing model — a benchmark script can call it with
        raw RDKit molecules.
    protocols:
        The standardizers to compare — any mix of composed
        :class:`~wawekit.services.reproducibility.protocol.StandardizationProtocol`
        objects and external
        :class:`~wawekit.services.reproducibility.standardizers.Standardizer`
        adapters (see that module). Untyped as ``object`` rather than either
        concrete type so this module has no import dependency on the adapter
        module for a comparison that never uses one.
    attribute_causes:
        Whether to run ablation-based cause attribution on labile molecules.
    progress:
        Optional ``(done, total)`` callback (kept untyped here to avoid a
        dependency on the loader module's callback type; any ``Callable[[int,
        int], None]`` works).

    Returns
    -------
    DivergenceRun
        Per-molecule results and dataset-level aggregates.

    """
    run = DivergenceRun(protocols=protocols)
    total = len(records)
    logger.info(
        "Analyzing divergence for %d molecule(s) across %d protocol(s)", total, len(protocols)
    )

    for done, (name, mol) in enumerate(records, start=1):
        result = analyze_molecule(mol, protocols, name=name, attribute_causes=attribute_causes)
        run.results.append(result)
        if progress is not None:
            progress(done, total)

    logger.info(
        "Divergence analysis complete: %d/%d labile (SMILES: %d, InChIKey: %d)",
        run.n_labile,
        total,
        run.n_smiles_labile,
        run.n_inchikey_labile,
    )
    return run
