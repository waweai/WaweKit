"""Structural alerts and drug-likeness filters.

Uses RDKit's built-in ``FilterCatalog`` to detect subgroups associated with
biological assay interference (PAINS), toxicity, or poor chemical stability
(Brenk, NIH catalogs).

This runs on the models/services layers without any Qt dependencies, so it can
be run headlessly.

Why this needs a batch runner (unlike :attr:`MoleculeRecord.smiles`)
----------------------------------------------------------------------
``FilterCatalog.GetMatches`` checks a molecule against several hundred SMARTS
patterns (PAINS A/B/C + Brenk + NIH combined) — cheap per molecule, but not
"repaint a table cell" cheap. Earlier, :attr:`MoleculeRecord.alerts` was read
directly from the table's ``data()`` method, meaning the *first paint* of any
row silently ran this on the GUI thread — noticeable stutter on real datasets.
:func:`compute_alerts_for_records` runs the same computation over a whole
dataset from a background worker instead, following the exact pattern
:mod:`~wawekit.services.chemistry.descriptors` established; the table checks
:attr:`MoleculeRecord.alerts_computed` and shows a blank/pending cell until
this pass fills the cache in place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

from rdkit import Chem
from rdkit.Chem import FilterCatalog

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_filter_catalog() -> FilterCatalog.FilterCatalog:
    """Lazily initialize the FilterCatalog with PAINS, Brenk, and NIH catalogs.

    Uses a robust fallback system to handle older or custom RDKit versions that
    might lack certain sub-catalog tags.
    """
    params = FilterCatalog.FilterCatalogParams()

    # Try loading the aggregate PAINS catalog
    try:
        params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    except Exception:
        # Fallback to individual PAINS groups if the aggregate isn't defined
        for catalog_enum in (
            FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_A,
            FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_B,
            FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS_C,
        ):
            try:
                params.AddCatalog(catalog_enum)
            except Exception:
                pass

    # Add Brenk and NIH catalogs
    for catalog_name in ("BRENK", "NIH"):
        try:
            catalog_enum = getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs, catalog_name)
            params.AddCatalog(catalog_enum)
        except Exception:
            pass

    return FilterCatalog.FilterCatalog(params)


def compute_alerts(mol: Chem.Mol) -> list[str]:
    """Check the given molecule against structural catalogs.

    Parameters
    ----------
    mol:
        A sanitized RDKit molecule object.

    Returns
    -------
    list[str]
        Descriptions of any matches (e.g. ``"PAINS: quinone_A"``), or empty list if clean.

    """
    if mol is None:
        return []  # nothing to check, not a failure worth reporting as one
    try:
        catalog = _get_filter_catalog()
        matches = catalog.GetMatches(mol)
        return [match.GetDescription() for match in matches]
    except Exception as exc:
        logger.exception("Failed to run FilterCatalog on molecule")
        return [f"Error running alerts: {exc}"]


@dataclass(slots=True)
class AlertReport:
    """Outcome of a batch alerts run.

    Attributes
    ----------
    records:
        The records the run covered (the same objects that were passed in —
        alerts are cached on them in place, exactly like descriptors).
    computed:
        How many molecules were freshly checked this run.
    reused:
        How many already had a cached result and were skipped.
    with_alerts:
        How many computed molecules triggered at least one warning.

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    computed: int = 0
    reused: int = 0
    with_alerts: int = 0

    @property
    def n_records(self) -> int:
        """Number of records covered by the run."""
        return len(self.records)


def compute_alerts_for_records(
    records: list[MoleculeRecord],
    recompute: bool = False,
    progress: ProgressCallback | None = None,
) -> AlertReport:
    """Compute and cache structural alerts for every record that lacks them.

    Runs the same per-molecule check as :func:`compute_alerts`, but over a
    whole dataset with progress reporting — meant to run on a background
    worker (see :mod:`wawekit.gui.main_window`), never on the GUI thread.
    Mirrors :func:`~wawekit.services.chemistry.descriptors.compute_descriptors`
    exactly: cache in place, one bad molecule never aborts the run
    (``compute_alerts`` itself already never raises).

    Parameters
    ----------
    records:
        Dataset to process. Each record's ``alerts`` cache is filled in
        place; nothing else about the record is touched.
    recompute:
        If ``True``, recheck even records that already have a cached result.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    AlertReport
        Counts describing the run.

    """
    report = AlertReport(records=list(records))
    total = len(records)
    logger.info("Computing structural alerts for %d record(s)", total)

    for done, record in enumerate(records, start=1):
        if record.alerts_computed and not recompute:
            report.reused += 1
        else:
            if recompute:
                record.invalidate_alerts()
            if record.alerts:
                report.with_alerts += 1
            report.computed += 1
        if progress is not None:
            progress(done, total)

    logger.info(
        "Alerts audit complete: %d computed (%d with warnings), %d reused",
        report.computed,
        report.with_alerts,
        report.reused,
    )
    return report
