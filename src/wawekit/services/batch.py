"""Batch processing: run a configured pipeline over the dataset, unattended.

Every chemistry service built so far — standardization, descriptors,
fingerprints, scaffolds, clustering — is Qt-free, takes a ``progress`` callback,
and returns a report. That uniformity is what this module cashes in: a
:class:`BatchConfig` is an ordered recipe of which of those steps to run (with
their options), and :func:`run_batch` chains them, threading the records through
and finishing with an optional CSV/SDF export.

This is where every frozen options dataclass (``StandardizationOptions``,
``FingerprintOptions``, ``ClusterOptions``, …) pays off: a pipeline is just those
objects in a container, so it is inspectable and — in a later module — saveable.

Cancellation
------------
A long batch must be interruptible, which nothing before it needed. The GUI sets
a :class:`threading.Event`; the runner checks it between steps and, through a
wrapped progress callback, *within* a step at each progress tick.

The signal it raises, :class:`BatchCancelled`, deliberately derives from
**BaseException**, not Exception. The chemistry services wrap each molecule in
``except Exception`` so one bad structure can't abort a run — and a cancellation
raised inside such a loop must *not* be mistaken for a bad molecule. Deriving
from BaseException (like ``KeyboardInterrupt``) means those handlers let it
straight through, and only :func:`run_batch` — which catches it explicitly —
stops the pipeline.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.clustering import ClusterOptions, cluster_molecules
from wawekit.services.chemistry.descriptors import compute_descriptors
from wawekit.services.chemistry.fingerprints import compute_fingerprints
from wawekit.services.chemistry.scaffolds import compute_scaffolds
from wawekit.services.chemistry.standardizer import StandardizationOptions, standardize_records
from wawekit.services.io.molecule_exporter import export_csv, export_sdf
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


class BatchCancelled(BaseException):
    """Raised to unwind a running batch when the user cancels.

    Derives from :class:`BaseException` so the chemistry services'
    ``except Exception`` per-molecule handlers cannot swallow it.
    """


class ExportFormat(StrEnum):
    """Output format for the batch's export step."""

    CSV = "CSV"
    SDF = "SDF"


@dataclass(frozen=True, slots=True)
class BatchConfig:
    """A batch pipeline: which steps to run, in fixed order, then export.

    A step is *off* when its field is ``None`` (for option-bearing steps) or
    ``False`` (for option-less ones). The fixed order — standardize, descriptors,
    fingerprints, scaffolds, cluster, export — is the only order that makes
    chemical sense (standardize before anything is measured; export last).

    Attributes
    ----------
    standardize:
        Standardization options, or ``None`` to skip.
    descriptors:
        Whether to compute descriptors.
    fingerprints:
        Fingerprint options, or ``None`` to skip.
    scaffolds:
        Whether to analyse scaffolds.
    cluster:
        Clustering options, or ``None`` to skip.
    export_path:
        Where to write results, or ``None`` to skip export.
    export_format:
        CSV or SDF (used only when ``export_path`` is set).

    """

    standardize: StandardizationOptions | None = None
    descriptors: bool = False
    fingerprints: FingerprintOptions | None = None
    scaffolds: bool = False
    cluster: ClusterOptions | None = None
    export_path: Path | None = None
    export_format: ExportFormat = ExportFormat.CSV

    @property
    def has_any_step(self) -> bool:
        """Whether at least one step is enabled."""
        return any(
            (
                self.standardize is not None,
                self.descriptors,
                self.fingerprints is not None,
                self.scaffolds,
                self.cluster is not None,
                self.export_path is not None,
            )
        )


@dataclass(slots=True)
class BatchResult:
    """Outcome of a batch run.

    Attributes
    ----------
    records:
        The dataset after the pipeline (new objects if standardization ran).
    summaries:
        One human-readable line per step that ran.
    cancelled:
        Whether the user cancelled before the pipeline finished.
    export_path:
        Where results were written, if the export step ran.
    exported:
        How many records were exported.

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    cancelled: bool = False
    export_path: Path | None = None
    exported: int = 0


#: A pipeline step: given records and a progress callback, return the (possibly
#: new) records and a one-line summary of what it did.
_Step = Callable[[list[MoleculeRecord], ProgressCallback], tuple[list[MoleculeRecord], str]]


def _build_steps(config: BatchConfig, result: BatchResult) -> list[tuple[str, _Step]]:
    """Assemble the ordered list of enabled steps from ``config``."""
    steps: list[tuple[str, _Step]] = []

    if config.standardize is not None:
        options = config.standardize

        def standardize(records: list[MoleculeRecord], progress: ProgressCallback):
            report = standardize_records(records, options, progress=progress)
            summary = (
                f"Standardize: {report.n_records} kept, {report.n_changed} changed, "
                f"{report.duplicates_removed} duplicate(s) removed"
            )
            return report.records, summary

        steps.append(("Standardize", standardize))

    if config.descriptors:

        def descriptors(records: list[MoleculeRecord], progress: ProgressCallback):
            report = compute_descriptors(records, progress=progress)
            return records, f"Descriptors: {report.computed} computed, {report.reused} reused"

        steps.append(("Descriptors", descriptors))

    if config.fingerprints is not None:
        fp_options = config.fingerprints

        def fingerprints(records: list[MoleculeRecord], progress: ProgressCallback):
            report = compute_fingerprints(records, fp_options, progress=progress)
            return records, f"Fingerprints ({report.options.label}): {report.computed} computed"

        steps.append(("Fingerprints", fingerprints))

    if config.scaffolds:

        def scaffolds(records: list[MoleculeRecord], progress: ProgressCallback):
            report = compute_scaffolds(records, progress=progress)
            return records, f"Scaffolds: {report.computed} computed"

        steps.append(("Scaffolds", scaffolds))

    if config.cluster is not None:
        cluster_options = config.cluster

        def cluster(records: list[MoleculeRecord], progress: ProgressCallback):
            report = cluster_molecules(records, cluster_options, progress=progress)
            return records, f"Cluster: {report.n_clusters} cluster(s)"

        steps.append(("Cluster", cluster))

    if config.export_path is not None:
        path = config.export_path
        fmt = config.export_format

        def export(records: list[MoleculeRecord], progress: ProgressCallback):
            count = (
                export_sdf(records, path) if fmt == ExportFormat.SDF else export_csv(records, path)
            )
            result.export_path = path
            result.exported = count
            progress(len(records), len(records))  # export is one atomic step
            return records, f"Export: {count} record(s) → {path.name}"

        steps.append(("Export", export))

    return steps


def run_batch(
    records: list[MoleculeRecord],
    config: BatchConfig,
    progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> BatchResult:
    """Run the configured pipeline over ``records``.

    Parameters
    ----------
    records:
        The dataset to process.
    config:
        Which steps to run and where to export.
    progress:
        Optional ``(done, total)`` callback. Progress is cumulative across steps,
        so the bar fills smoothly over the whole pipeline.
    cancel_event:
        Optional event; when set, the run stops at the next step boundary or
        progress tick and returns a partial, ``cancelled`` result.

    Returns
    -------
    BatchResult
        The processed records and a per-step summary.

    """
    result = BatchResult(records=list(records))
    steps = _build_steps(config, result)
    if not steps:
        return result

    # Even per-step spacing keeps the bar smooth even though standardization may
    # change the record count mid-run.
    per_step = max(1, len(records))
    total_work = len(steps) * per_step
    logger.info("Running batch: %d step(s) over %d record(s)", len(steps), len(records))

    def step_progress(base: int) -> ProgressCallback:
        def report(done: int, _total: int) -> None:
            if cancel_event is not None and cancel_event.is_set():
                raise BatchCancelled
            if progress is not None:
                progress(min(base + done, total_work), total_work)

        return report

    current = result.records
    try:
        for index, (label, step) in enumerate(steps):
            if cancel_event is not None and cancel_event.is_set():
                raise BatchCancelled
            logger.info("Batch step %d/%d: %s", index + 1, len(steps), label)
            current, summary = step(current, step_progress(index * per_step))
            result.summaries.append(summary)
            if progress is not None:
                progress((index + 1) * per_step, total_work)
    except BatchCancelled:
        result.cancelled = True
        result.summaries.append("— cancelled by user —")
        logger.info("Batch cancelled after %d step(s)", len(result.summaries) - 1)

    result.records = current
    return result
