"""Substructure searching.

Parses a query pattern once and asks every molecule whether it contains it,
recording *where* (the matched atom indices) so the structure views can
highlight the hit.

RDKit
-----
* :func:`rdkit.Chem.MolFromSmarts` — parse a **SMARTS** query (the query
  language: atom/bond primitives, wildcards, recursion). Returns ``None`` on a
  bad pattern rather than raising.
* :func:`rdkit.Chem.MolFromSmiles` — parse a plain SMILES read as a query.
* ``mol.GetSubstructMatches(query, uniquify=True)`` — every distinct match, each
  a tuple of the molecule's atom indices that the query mapped onto.

Design rules (the shared seam):

* **A report, not just results** — counts and per-molecule failures as data.
* **One bad molecule never aborts the run.**
* **Cache in place, clear staleness** — the hit attaches to the record (so the
  column, the filter and the highlighting can read it); a record that cannot be
  searched has its old hit cleared, never left stale.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem, rdBase

from wawekit.models.molecule import MoleculeRecord
from wawekit.models.substructure import SubstructureHit, SubstructureQuery
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SubstructureReport:
    """Outcome of a substructure search.

    Attributes
    ----------
    query:
        The query that was run.
    records:
        The records the search covered (hits cached on them in place).
    matched:
        How many molecules contained the query.
    failures:
        ``"name: message"`` for each molecule RDKit could not search.

    """

    query: SubstructureQuery
    records: list[MoleculeRecord] = field(default_factory=list)
    matched: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records searched."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of molecules that could not be searched."""
        return len(self.failures)


def parse_query(pattern: str, is_smarts: bool = True) -> Chem.Mol | None:
    """Parse a query ``pattern`` into a query molecule, or ``None`` if invalid.

    Mirrors :func:`~wawekit.services.io.molecule_loader.parse_smiles`: it returns
    ``None`` rather than raising (an invalid pattern is the normal state of a box
    someone is mid-type in) and mutes RDKit's stderr, so a dialog can validate on
    every keystroke without the console filling with parse errors — and without
    importing RDKit itself.

    Parameters
    ----------
    pattern:
        The query text. Surrounding whitespace is ignored.
    is_smarts:
        Parse as SMARTS (``True``) or plain SMILES (``False``).

    Returns
    -------
    Chem.Mol | None
        The query molecule, or ``None`` if it could not be parsed.

    """
    text = pattern.strip()
    if not text:
        return None
    with rdBase.BlockLogs():
        return Chem.MolFromSmarts(text) if is_smarts else Chem.MolFromSmiles(text)


def search_substructure(
    records: list[MoleculeRecord],
    query: SubstructureQuery,
    progress: ProgressCallback | None = None,
) -> SubstructureReport:
    """Search every record for ``query`` and cache a :class:`SubstructureHit`.

    Parameters
    ----------
    records:
        Dataset to search. Each record's ``substructure_match`` is set (matched
        or not), or cleared if it cannot be searched.
    query:
        The pattern to search for.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    SubstructureReport
        Counts and any per-molecule failures.

    Raises
    ------
    ValueError
        If the query pattern cannot be parsed.

    """
    query_mol = parse_query(query.pattern, query.is_smarts)
    if query_mol is None:
        kind = "SMARTS" if query.is_smarts else "SMILES"
        raise ValueError(f"Invalid {kind} query: {query.pattern!r}")

    report = SubstructureReport(query=query, records=list(records))
    total = len(records)
    logger.info("Substructure search over %d record(s): %s", total, query.label)

    for done, record in enumerate(records, start=1):
        try:
            matches = record.mol.GetSubstructMatches(query_mol, uniquify=True)
            record.substructure_match = SubstructureHit(query=query, matches=tuple(matches))
            if matches:
                report.matched += 1
        except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
            logger.exception("Substructure match failed for %s", record.name)
            record.substructure_match = None  # clear any stale hit
            report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "Substructure search complete: %d matched, %d failure(s)", report.matched, report.n_failed
    )
    return report
