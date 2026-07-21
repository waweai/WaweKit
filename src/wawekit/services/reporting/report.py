"""Report orchestration: compute a summary, then write the chosen formats.

A *report* is a shareable snapshot of the dataset — summary statistics plus a
grid of molecules with their depictions and key properties. This module computes
the format-independent parts (a :class:`ReportSummary`) and dispatches to the
HTML and PDF writers, so both formats show identical numbers.

Kept in ``services`` and Qt-free: depictions come from
:mod:`wawekit.services.rendering.mol_renderer` (SVG for HTML, Cairo PNG for PDF),
neither of which touches Qt, so a report can be generated from the GUI worker, a
CLI, or a notebook.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from wawekit import __version__
from wawekit.models.descriptors import DESCRIPTOR_SPECS, DescriptorSpec
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


class ReportFormat(StrEnum):
    """A report output format."""

    HTML = "HTML"
    PDF = "PDF"


@dataclass(frozen=True, slots=True)
class ReportConfig:
    """What to put in a report and where to write it.

    Attributes
    ----------
    title:
        Report heading.
    output_path:
        Base path; each chosen format is written with its own suffix
        (``.html`` / ``.pdf``).
    formats:
        Which formats to produce.
    max_molecules:
        Cap on molecules shown in the grid (a report is a summary, not a dump);
        the summary statistics still cover the whole dataset.
    include_depictions:
        Whether to draw each molecule's 2D structure (the slow part).

    """

    title: str = "Wawekit Report"
    output_path: Path = Path("report")
    formats: tuple[ReportFormat, ...] = (ReportFormat.HTML,)
    max_molecules: int = 200
    include_depictions: bool = True


@dataclass(frozen=True, slots=True)
class DescriptorStat:
    """Min / mean / max of one descriptor across the computed molecules."""

    spec: DescriptorSpec
    minimum: float
    mean: float
    maximum: float


@dataclass(slots=True)
class ReportSummary:
    """Format-independent facts about the dataset, shown in the report header.

    Attributes
    ----------
    title:
        The report title.
    generated:
        Timestamp string.
    version:
        Wawekit version that produced the report.
    n_molecules:
        Total molecules in the dataset.
    descriptor_stats:
        Per-descriptor min/mean/max, empty if descriptors were not computed.
    lipinski_pass:
        How many molecules pass Lipinski's Rule of 5 (``None`` if unknown).
    n_clusters:
        Distinct clusters, or ``None`` if not clustered.
    n_scaffolds:
        Distinct Murcko scaffolds, or ``None`` if not analysed.

    """

    title: str
    generated: str
    version: str
    n_molecules: int
    descriptor_stats: list[DescriptorStat] = field(default_factory=list)
    lipinski_pass: int | None = None
    n_clusters: int | None = None
    n_scaffolds: int | None = None


@dataclass(slots=True)
class ReportResult:
    """Outcome of a report run: which files were written."""

    paths: list[Path] = field(default_factory=list)
    n_molecules: int = 0


def build_summary(records: list[MoleculeRecord], title: str) -> ReportSummary:
    """Compute the format-independent summary of ``records``.

    Statistics are computed only over the molecules that actually have the value
    (descriptors, clusters, scaffolds are all optional), so a partially-analysed
    dataset reports what it knows and stays silent about the rest.
    """
    with_descriptors = [r.descriptors for r in records if r.descriptors is not None]
    stats: list[DescriptorStat] = []
    if with_descriptors:
        for spec in DESCRIPTOR_SPECS:
            values = [float(spec.getter(d)) for d in with_descriptors]
            stats.append(
                DescriptorStat(
                    spec=spec,
                    minimum=min(values),
                    mean=statistics.fmean(values),
                    maximum=max(values),
                )
            )
    lipinski_pass = (
        sum(1 for d in with_descriptors if d.passes_lipinski) if with_descriptors else None
    )

    clustered = [r.cluster for r in records if r.cluster is not None]
    n_clusters = clustered[0].run.n_clusters if clustered else None

    scaffolds = {
        r.scaffold.murcko_smiles
        for r in records
        if r.scaffold is not None and r.scaffold.has_ring_system
    }
    n_scaffolds = len(scaffolds) if any(r.scaffold is not None for r in records) else None

    return ReportSummary(
        title=title,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        version=__version__,
        n_molecules=len(records),
        descriptor_stats=stats,
        lipinski_pass=lipinski_pass,
        n_clusters=n_clusters,
        n_scaffolds=n_scaffolds,
    )


def generate_report(
    records: list[MoleculeRecord],
    config: ReportConfig,
    progress: ProgressCallback | None = None,
) -> ReportResult:
    """Generate the configured report format(s) and return the written paths.

    Parameters
    ----------
    records:
        The dataset to report on. Depictions are drawn for at most
        ``config.max_molecules`` of them; the summary covers all.
    config:
        Title, formats, and output path.
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    ReportResult
        The paths written.

    """
    # Imported here so the (heavier) writers load only when a report is run.
    from wawekit.services.reporting.html_writer import write_html
    from wawekit.services.reporting.pdf_writer import write_pdf

    summary = build_summary(records, config.title)
    shown = records[: config.max_molecules]
    truncated = len(records) - len(shown)
    result = ReportResult(n_molecules=len(records))

    logger.info(
        "Generating %s report(s) for %d molecule(s)",
        ", ".join(config.formats),
        len(records),
    )

    # Progress covers depiction work (per shown molecule) once per format.
    total = max(1, len(shown) * len(config.formats))
    done = 0

    def step(_i: int, _n: int) -> None:
        nonlocal done
        done += 1
        if progress is not None:
            progress(min(done, total), total)

    for fmt in config.formats:
        path = config.output_path.with_suffix(".html" if fmt == ReportFormat.HTML else ".pdf")
        writer = write_html if fmt == ReportFormat.HTML else write_pdf
        writer(shown, summary, config, truncated, path, step)
        result.paths.append(path)

    if progress is not None:
        progress(total, total)
    logger.info("Report(s) written: %s", ", ".join(p.name for p in result.paths))
    return result
