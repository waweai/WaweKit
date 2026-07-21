"""Molecular standardization pipeline.

Real-world datasets are chemically inconsistent: salts and solvents attached,
varying charge states, tautomer encodings, and — once those are fixed —
duplicate entries. Descriptors, fingerprints and clustering computed on
unstandardized data are silently wrong, so this pipeline runs *before* any of
them.

Built on RDKit's :mod:`rdkit.Chem.MolStandardize.rdMolStandardize`:

* ``Cleanup``                  — sanitize + normalize functional-group
  representations (e.g. the two common nitro drawings become one).
* ``LargestFragmentChooser``   — keep the parent molecule, dropping salt/solvent
  fragments (``.Cl``, ``.[Na+]``, water, ...).
* ``Uncharger``                — neutralize charges where chemically sensible
  (carboxylate → carboxylic acid) without touching quaternary nitrogens.
* ``TautomerEnumerator``       — canonical tautomer (2-hydroxypyridine and
  2-pyridone collapse to one form). Expensive → off by default.

Design rules (mirroring the loader):

* **Immutable in, new records out** — input records are never mutated; failures
  keep the *original* record instead of silently dropping molecules.
* **A report, not just results** — every change is tracked (before/after SMILES
  and which steps fired) so users and papers have provenance.
* **Qt-free** — plain ``progress`` callback; runs identically in the GUI worker,
  a CLI, or a notebook.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem.MolStandardize import rdMolStandardize

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StandardizationOptions:
    """User-selected pipeline steps (order is fixed; flags enable/disable).

    Attributes
    ----------
    cleanup:
        Run RDKit ``Cleanup`` (sanitize + normalize representations).
    strip_salts:
        Keep only the largest fragment (removes salts/solvents).
    neutralize:
        Neutralize charges where chemically sensible.
    canonicalize_tautomer:
        Convert to RDKit's canonical tautomer (slow on large sets).
    remove_duplicates:
        Drop records whose standardized canonical SMILES was already seen.

    """

    cleanup: bool = True
    strip_salts: bool = True
    neutralize: bool = True
    canonicalize_tautomer: bool = False
    remove_duplicates: bool = True


@dataclass(slots=True)
class RecordChange:
    """Provenance for one molecule the pipeline modified."""

    name: str
    before_smiles: str
    after_smiles: str
    steps: list[str]

    def __str__(self) -> str:
        """Return a one-line human-readable change description."""
        applied = ", ".join(self.steps)
        return f"{self.name} [{applied}]: {self.before_smiles} → {self.after_smiles}"


@dataclass(slots=True)
class StandardizationReport:
    """Complete outcome of a standardization run."""

    records: list[MoleculeRecord] = field(default_factory=list)
    changed: list[RecordChange] = field(default_factory=list)
    duplicates_removed: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records in the standardized dataset."""
        return len(self.records)

    @property
    def n_changed(self) -> int:
        """Number of molecules the pipeline modified."""
        return len(self.changed)


def _standardize_mol(
    mol: Chem.Mol,
    options: StandardizationOptions,
    chooser: rdMolStandardize.LargestFragmentChooser,
    uncharger: rdMolStandardize.Uncharger,
    tautomerizer: rdMolStandardize.TautomerEnumerator,
) -> tuple[Chem.Mol, list[str]]:
    """Run the enabled steps on one molecule, recording which ones changed it.

    The heavyweight helper objects are created once by the caller and reused
    across the whole dataset (constructing a TautomerEnumerator per molecule
    would dominate the runtime).
    """
    steps: list[str] = []
    current = mol

    def advance(candidate: Chem.Mol, step: str) -> Chem.Mol:
        """Adopt ``candidate`` and log ``step`` if it altered the molecule."""
        nonlocal steps
        if Chem.MolToSmiles(candidate) != Chem.MolToSmiles(current):
            steps.append(step)
        return candidate

    if options.cleanup:
        current = advance(rdMolStandardize.Cleanup(current), "cleanup")
    if options.strip_salts:
        current = advance(chooser.choose(current), "strip-salts")
    if options.neutralize:
        current = advance(uncharger.uncharge(current), "neutralize")
    if options.canonicalize_tautomer:
        current = advance(tautomerizer.Canonicalize(current), "tautomer")
    return current, steps


def standardize_records(
    records: list[MoleculeRecord],
    options: StandardizationOptions,
    progress: ProgressCallback | None = None,
) -> StandardizationReport:
    """Standardize ``records`` according to ``options``.

    Parameters
    ----------
    records:
        Input dataset; never mutated.
    options:
        Which pipeline steps to run.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    StandardizationReport
        New records plus full provenance (changes, duplicates, failures).

    """
    report = StandardizationReport()
    chooser = rdMolStandardize.LargestFragmentChooser()
    uncharger = rdMolStandardize.Uncharger()
    tautomerizer = rdMolStandardize.TautomerEnumerator()

    seen: set[str] = set()
    total = len(records)
    logger.info("Standardizing %d record(s) with %s", total, options)

    for done, record in enumerate(records, start=1):
        try:
            new_mol, steps = _standardize_mol(record.mol, options, chooser, uncharger, tautomerizer)
            new_smiles = Chem.MolToSmiles(new_mol)

            if options.remove_duplicates:
                if new_smiles in seen:
                    report.duplicates_removed += 1
                    if progress is not None:
                        progress(done, total)
                    continue
                seen.add(new_smiles)

            if steps:
                report.changed.append(
                    RecordChange(
                        name=record.name,
                        before_smiles=record.smiles,
                        after_smiles=new_smiles,
                        steps=steps,
                    )
                )
                new_record = MoleculeRecord(
                    mol=new_mol,
                    name=record.name,
                    source=record.source,
                    index_in_source=record.index_in_source,
                    properties=dict(record.properties),
                )
            else:
                new_record = record  # untouched: reuse, no copy needed
            report.records.append(new_record)
        except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
            logger.exception("Standardization failed for %s", record.name)
            report.failures.append(f"{record.name}: {exc}")
            report.records.append(record)  # keep the original, never drop silently
        if progress is not None:
            progress(done, total)

    logger.info(
        "Standardization complete: %d record(s), %d changed, %d dup(s) removed, %d failure(s)",
        report.n_records,
        report.n_changed,
        report.duplicates_removed,
        len(report.failures),
    )
    return report
