"""Molecular descriptor computation.

Descriptors are the basic vocabulary of computational chemistry: numbers
derived from a structure that stand in for physical behaviour. This service
computes the classic drug-likeness panel — the inputs to Lipinski's Rule of 5 —
and caches the result on each record.

RDKit provides the science:

* ``Descriptors.MolWt``            — average molecular mass.
* ``Descriptors.MolLogP``          — Crippen logP (lipophilicity).
* ``Descriptors.TPSA``             — topological polar surface area.
* ``Descriptors.NumHDonors`` / ``NumHAcceptors`` — Lipinski H-bond counts.
* ``Descriptors.NumRotatableBonds``— flexibility.
* ``rdMolDescriptors.CalcNumRings``— ring count (SSSR).

Design rules (the same seam as
:mod:`~wawekit.services.chemistry.standardizer`, which is the point — proving
the pattern generalizes):

* **Qt-free** — a plain ``progress`` callback, so this runs unchanged in the
  GUI worker, a CLI, or a notebook.
* **A report, not just results** — counts and per-molecule failures come back
  as data the caller can present.
* **One bad molecule never aborts the run** — failures are collected and the
  record simply keeps ``descriptors = None``.

Why this mutates records (and the standardizer does not)
--------------------------------------------------------
:func:`standardize_records` returns *new* records because it changes chemistry.
Descriptors change nothing: they are a cache of values already implied by the
structure, like :attr:`MoleculeRecord.smiles`. Filling the cache in place means
the GUI table keeps the exact record objects it already holds — no dataset
swap, no lost selection, just a repaint of the affected columns.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors

from wawekit.models.descriptors import DescriptorSet
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DescriptorReport:
    """Outcome of a descriptor run.

    Attributes
    ----------
    records:
        The records the run covered (the same objects that were passed in —
        descriptors are cached on them in place).
    computed:
        How many molecules had descriptors calculated this run.
    reused:
        How many already had a cached set and were skipped.
    failures:
        ``"name: message"`` for each molecule RDKit could not handle.

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    computed: int = 0
    reused: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records covered by the run."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of molecules whose descriptors could not be computed."""
        return len(self.failures)


def compute_descriptor_set(mol: Chem.Mol) -> DescriptorSet:
    """Compute the full descriptor panel for one molecule.

    Parameters
    ----------
    mol:
        A sanitized RDKit molecule.

    Returns
    -------
    DescriptorSet
        The computed values (Lipinski violations are derived on demand from
        these, not stored separately).

    """
    return DescriptorSet(
        molecular_weight=Descriptors.MolWt(mol),
        logp=Descriptors.MolLogP(mol),
        tpsa=Descriptors.TPSA(mol),
        h_bond_donors=Descriptors.NumHDonors(mol),
        h_bond_acceptors=Descriptors.NumHAcceptors(mol),
        rotatable_bonds=Descriptors.NumRotatableBonds(mol),
        ring_count=rdMolDescriptors.CalcNumRings(mol),
    )


def compute_descriptors(
    records: list[MoleculeRecord],
    recompute: bool = False,
    progress: ProgressCallback | None = None,
) -> DescriptorReport:
    """Compute and cache descriptors for every record that lacks them.

    Parameters
    ----------
    records:
        Dataset to process. Each record's ``descriptors`` field is filled in
        place; nothing else about the record is touched.
    recompute:
        If ``True``, recalculate even for records that already have a cached
        set (useful after an external structural edit).
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    DescriptorReport
        Counts plus any per-molecule failures.

    """
    report = DescriptorReport(records=list(records))
    total = len(records)
    logger.info("Computing descriptors for %d record(s) (recompute=%s)", total, recompute)

    for done, record in enumerate(records, start=1):
        if record.descriptors is not None and not recompute:
            report.reused += 1
        else:
            try:
                record.descriptors = compute_descriptor_set(record.mol)
                report.computed += 1
            except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
                logger.exception("Descriptor computation failed for %s", record.name)
                report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "Descriptors complete: %d computed, %d reused, %d failure(s)",
        report.computed,
        report.reused,
        report.n_failed,
    )
    return report
