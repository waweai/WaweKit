"""File-format conversion service.

Converts between molecule file formats (CSV, SDF, MOL, SMILES) by reading
the input with :func:`~wawekit.services.io.molecule_loader.load_file` and
writing to the target format with the appropriate exporter.

Kept Qt-free in ``services/io`` so it can run in a worker thread, CLI,
or notebook.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from wawekit.services.io.molecule_exporter import (
    export_csv,
    export_mol,
    export_sdf,
    export_smiles,
)
from wawekit.services.io.molecule_loader import (
    LoadReport,
    load_file,
)

logger = logging.getLogger(__name__)

#: Callback signature for progress reporting: ``progress(done, total)``.
ProgressCallback = Callable[[int, int], None]

#: Output formats and their file-dialog labels.
OUTPUT_FORMATS: dict[str, str] = {
    "sdf": "SDF file (*.sdf)",
    "mol": "MOL file (*.mol)",
    "csv": "CSV file (*.csv)",
    "smiles": "SMILES file (*.smi)",
}

#: Map format key → default extension.
FORMAT_EXTENSIONS: dict[str, str] = {
    "sdf": ".sdf",
    "mol": ".mol",
    "csv": ".csv",
    "smiles": ".smi",
}


@dataclass(slots=True)
class ConversionReport:
    """Outcome of a file-format conversion."""

    input_path: Path
    output_path: Path
    input_format: str
    output_format: str
    n_read: int = 0
    n_written: int = 0
    n_errors: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether the conversion completed with at least one molecule written."""
        return self.n_written > 0


def convert_file(
    input_path: Path,
    output_path: Path,
    output_format: str,
    progress: ProgressCallback | None = None,
) -> ConversionReport:
    """Convert ``input_path`` to ``output_format`` and write to ``output_path``.

    Parameters
    ----------
    input_path:
        Source file (SDF, MOL, SMILES, or CSV).
    output_path:
        Destination file path.
    output_format:
        Target format key: ``"sdf"``, ``"mol"``, ``"csv"``, or ``"smiles"``.
    progress:
        Optional ``(done, total)`` callback.

    Returns
    -------
    ConversionReport
        Summary of the conversion.

    """
    report = ConversionReport(
        input_path=input_path,
        output_path=output_path,
        input_format=input_path.suffix.lower().lstrip("."),
        output_format=output_format,
    )

    # Step 1: Load input
    try:
        load_report: LoadReport = load_file(input_path, progress)
    except Exception as exc:
        report.errors.append(f"Failed to read input: {exc}")
        return report

    report.n_read = load_report.n_loaded
    report.n_errors = load_report.n_failed
    report.errors.extend(str(e) for e in load_report.errors)

    if not load_report.records:
        report.errors.append("No molecules could be read from the input file.")
        return report

    # Step 2: Write output
    try:
        if output_format == "csv":
            report.n_written = export_csv(load_report.records, output_path)
        elif output_format == "sdf":
            report.n_written = export_sdf(load_report.records, output_path)
        elif output_format == "mol":
            if len(load_report.records) > 1:
                report.errors.append(
                    f"MOL format supports only 1 molecule, but the input has "
                    f"{len(load_report.records)}. Writing only the first molecule."
                )
            export_mol(load_report.records[0], output_path)
            report.n_written = 1
        elif output_format == "smiles":
            report.n_written = export_smiles(load_report.records, output_path)
        else:
            report.errors.append(f"Unknown output format: {output_format!r}")
    except Exception as exc:
        logger.exception("Conversion write failed")
        report.errors.append(f"Failed to write output: {exc}")

    logger.info(
        "Converted %s → %s: %d read, %d written, %d error(s)",
        input_path.name,
        output_path.name,
        report.n_read,
        report.n_written,
        report.n_errors,
    )
    return report
