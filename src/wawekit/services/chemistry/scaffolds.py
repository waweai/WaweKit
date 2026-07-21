"""Bemis–Murcko scaffold computation and grouping.

Two operations live here:

* :func:`compute_scaffolds` turns each molecule into its scaffold and caches the
  result on the record — the same in-place discipline as
  :mod:`~wawekit.services.chemistry.descriptors`, because a scaffold is intrinsic
  to the structure (filling the cache changes nothing about the molecule).
* :func:`group_scaffolds` aggregates a dataset by shared scaffold, ranked by how
  many molecules fall under each. This is the analytical payload — *scaffold
  diversity* — and it is a read-only view over records, so it returns fresh
  :class:`ScaffoldGroup` objects rather than mutating anything.

RDKit provides the science, in ``rdkit.Chem.Scaffolds.MurckoScaffold``:

* ``GetScaffoldForMol(mol)`` — the exact Bemis–Murcko scaffold (ring systems +
  linkers, side chains removed). Returns an *empty* molecule for an acyclic
  input, which we surface honestly as "no scaffold" rather than a crash.
* ``MakeScaffoldGeneric(scaffold)`` — collapses the scaffold to its graph: every
  atom carbon, every bond single.

Design rules (the shared seam, proven across Modules 4–7):

* **Qt-free** — a plain ``progress`` callback, so this runs unchanged in the GUI
  worker, a CLI, or a notebook.
* **A report, not just results** — counts and per-molecule failures come back as
  data the caller presents.
* **One bad molecule never aborts the run** — failures are collected and the
  record simply keeps ``scaffold = None``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ACYCLIC_LABEL, ScaffoldRepresentation, ScaffoldResult
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScaffoldReport:
    """Outcome of a scaffold-computation run.

    Attributes
    ----------
    records:
        The records the run covered (the same objects passed in — scaffolds are
        cached on them in place).
    computed:
        How many molecules had a scaffold calculated this run.
    reused:
        How many already had a cached scaffold and were skipped.
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
        """Number of molecules whose scaffold could not be computed."""
        return len(self.failures)


@dataclass(slots=True)
class ScaffoldGroup:
    """One scaffold and the molecules that share it.

    Attributes
    ----------
    key:
        The scaffold SMILES the members share (``""`` for the acyclic group).
    representation:
        Which representation the grouping used, so a group knows how it was made.
    members:
        The records in this group, in their original dataset order.

    """

    key: str
    representation: ScaffoldRepresentation
    members: list[MoleculeRecord] = field(default_factory=list)

    @property
    def size(self) -> int:
        """Number of molecules sharing this scaffold."""
        return len(self.members)

    @property
    def is_acyclic(self) -> bool:
        """Whether this is the group of molecules with no ring system."""
        return self.key == ""

    @property
    def label(self) -> str:
        """Display label: the scaffold SMILES, or a friendly acyclic note."""
        return ACYCLIC_LABEL if self.is_acyclic else self.key


def compute_scaffold(mol: Chem.Mol) -> ScaffoldResult:
    """Compute the exact and generic scaffolds for one molecule.

    Parameters
    ----------
    mol:
        A sanitized RDKit molecule.

    Returns
    -------
    ScaffoldResult
        Both scaffold SMILES, or an empty (acyclic) result if the molecule has
        no ring system.

    """
    scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    if scaffold.GetNumAtoms() == 0:
        # Acyclic molecule: no ring system, therefore no scaffold. Represent it
        # honestly rather than inventing one.
        return ScaffoldResult(murcko_smiles="", generic_smiles="", has_ring_system=False)

    murcko_smiles = Chem.MolToSmiles(scaffold)
    generic = MurckoScaffold.MakeScaffoldGeneric(scaffold)
    generic_smiles = Chem.MolToSmiles(generic)
    return ScaffoldResult(
        murcko_smiles=murcko_smiles,
        generic_smiles=generic_smiles,
        has_ring_system=True,
    )


def compute_scaffolds(
    records: list[MoleculeRecord],
    recompute: bool = False,
    progress: ProgressCallback | None = None,
) -> ScaffoldReport:
    """Compute and cache scaffolds for every record that lacks one.

    Parameters
    ----------
    records:
        Dataset to process. Each record's ``scaffold`` field is filled in place;
        nothing else about the record is touched.
    recompute:
        If ``True``, recalculate even for records that already have a scaffold.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    ScaffoldReport
        Counts plus any per-molecule failures.

    """
    report = ScaffoldReport(records=list(records))
    total = len(records)
    logger.info("Computing scaffolds for %d record(s) (recompute=%s)", total, recompute)

    for done, record in enumerate(records, start=1):
        if record.scaffold is not None and not recompute:
            report.reused += 1
        else:
            try:
                record.scaffold = compute_scaffold(record.mol)
                report.computed += 1
            except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
                logger.exception("Scaffold computation failed for %s", record.name)
                report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "Scaffolds complete: %d computed, %d reused, %d failure(s)",
        report.computed,
        report.reused,
        report.n_failed,
    )
    return report


def group_scaffolds(
    records: list[MoleculeRecord],
    representation: ScaffoldRepresentation = ScaffoldRepresentation.MURCKO,
) -> list[ScaffoldGroup]:
    """Group records by shared scaffold, ranked by group size (largest first).

    Records whose scaffold has not been computed are skipped — they belong to no
    group until :func:`compute_scaffolds` has run.

    Parameters
    ----------
    records:
        Dataset to group.
    representation:
        Which scaffold form to group by (exact Murcko or generic framework).

    Returns
    -------
    list[ScaffoldGroup]
        Groups sorted by descending size, then by key for a stable order.

    """
    buckets: dict[str, list[MoleculeRecord]] = defaultdict(list)
    for record in records:
        if record.scaffold is None:
            continue
        buckets[record.scaffold.group_key(representation)].append(record)

    groups = [
        ScaffoldGroup(key=key, representation=representation, members=members)
        for key, members in buckets.items()
    ]
    # Largest groups first (the common cores), then by key so ties are stable.
    groups.sort(key=lambda g: (-g.size, g.key))
    logger.debug("Grouped into %d scaffold(s) by %s", len(groups), representation)
    return groups
