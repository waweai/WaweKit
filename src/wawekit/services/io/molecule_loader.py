"""Robust molecule file loading.

Reads SDF, MOL and SMILES files into :class:`~wawekit.models.molecule.MoleculeRecord`
objects, with two non-negotiable behaviors for real-world chemical data:

1. **Partial failure is normal.** A broken record must never abort the load;
   it is captured as a :class:`LoadError` and the remaining molecules still
   load. The GUI decides how to present failures.
2. **The loader is UI-free.** No Qt imports — it takes an optional plain
   ``progress(done, total)`` callback, so it is fully unit-testable and equally
   usable from a CLI or notebook.

RDKit concepts used here
------------------------
* :class:`rdkit.Chem.SDMolSupplier` — an indexed reader for multi-molecule SDF
  files. Supports ``len()`` and random access; yields ``None`` for records that
  fail parsing or *sanitization* (RDKit's valence/aromaticity validation).
* :func:`rdkit.Chem.MolFromSmiles` / :func:`rdkit.Chem.MolFromMolFile` —
  return ``None`` on failure rather than raising, so we translate ``None`` into
  a :class:`LoadError` with location information.
* ``mol.GetPropsAsDict()`` — data fields attached to an SDF record (activity
  values, IDs, ...) which we preserve on the :class:`MoleculeRecord`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from rdkit import Chem, rdBase

from wawekit.models.molecule import MoleculeRecord

logger = logging.getLogger(__name__)

#: Callback signature for progress reporting: ``progress(records_done, total)``.
ProgressCallback = Callable[[int, int], None]

#: Map of supported file extensions to a format key used for dispatch.
SUPPORTED_EXTENSIONS: dict[str, str] = {
    ".sdf": "sdf",
    ".mol": "mol",
    ".smi": "smiles",
    ".smiles": "smiles",
    ".txt": "smiles",
}

#: Emit a progress callback every N records (avoids flooding the GUI thread).
_PROGRESS_EVERY = 100


class UnsupportedFormatError(ValueError):
    """Raised when a file's extension is not a supported molecule format."""


@dataclass(slots=True)
class LoadError:
    """One record that could not be read, with enough context to locate it."""

    location: str  #: e.g. ``"record 5"`` or ``"line 12"``
    message: str

    def __str__(self) -> str:
        """Return ``location: message`` for display in dialogs and logs."""
        return f"{self.location}: {self.message}"


@dataclass(slots=True)
class LoadReport:
    """Complete outcome of loading one file: successes *and* failures."""

    source: Path
    fmt: str
    records: list[MoleculeRecord] = field(default_factory=list)
    errors: list[LoadError] = field(default_factory=list)

    @property
    def n_loaded(self) -> int:
        """Number of molecules successfully loaded."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of records that could not be read."""
        return len(self.errors)


def detect_format(path: Path) -> str:
    """Return the format key for ``path`` based on its extension.

    Raises
    ------
    UnsupportedFormatError
        If the extension is not in :data:`SUPPORTED_EXTENSIONS`.

    """
    fmt = SUPPORTED_EXTENSIONS.get(path.suffix.lower())
    if fmt is None:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise UnsupportedFormatError(
            f"Unsupported file type {path.suffix!r} for {path.name}. Supported: {supported}"
        )
    return fmt


def file_dialog_filter() -> str:
    """Build the Qt file-dialog name filter string from the supported extensions."""
    patterns = " ".join(f"*{ext}" for ext in sorted(SUPPORTED_EXTENSIONS))
    return f"Molecule files ({patterns});;All files (*)"


def parse_smiles(text: str, name: str = "query") -> MoleculeRecord | None:
    """Parse a single SMILES string into a record, or ``None`` if it is invalid.

    The file loaders above turn *files* into records; this turns one *typed
    string* into one. Module 7 needs it so a user can paste a structure to
    search for without first saving it to disk — and so the dialog that accepts
    that paste never has to import RDKit itself, which the layering rule
    (``gui -> services -> models -> core``) forbids.

    Returns ``None`` rather than raising: invalid SMILES is the *normal* state
    of a text box someone is halfway through typing, not an exceptional event.
    Callers use it to drive live validation.

    Parameters
    ----------
    text:
        The SMILES string. Surrounding whitespace is ignored.
    name:
        Display name for the resulting record.

    Returns
    -------
    MoleculeRecord | None
        A record with no source file (``source`` is ``None``), or ``None`` if
        RDKit could not parse and sanitize the string.

    """
    smiles = text.strip()
    if not smiles:
        return None
    # RDKit reports parse failures by returning None *and* writing to stderr; it
    # does not raise. The stderr half is unwanted here: live validation parses on
    # every keystroke, so "C1CC" mid-typing would spew a Parse Error line per
    # character. BlockLogs mutes RDKit for this call only — we already surface
    # the failure through the return value.
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        logger.debug("Rejected SMILES %r", smiles)
        return None
    return MoleculeRecord(mol=mol, name=name)


def load_file(path: Path, progress: ProgressCallback | None = None) -> LoadReport:
    """Load every molecule from ``path`` into a :class:`LoadReport`.

    Parameters
    ----------
    path:
        The molecule file to read.
    progress:
        Optional ``(done, total)`` callback invoked periodically; safe to pass
        a Qt signal's ``emit`` from a worker thread.

    Raises
    ------
    UnsupportedFormatError
        If the extension is not supported.
    FileNotFoundError
        If ``path`` does not exist.

    """
    fmt = detect_format(path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    logger.info("Loading %s (%s format)", path, fmt)
    if fmt == "sdf":
        report = _load_sdf(path, progress)
    elif fmt == "mol":
        report = _load_mol(path)
    else:
        report = _load_smiles(path, progress)

    logger.info(
        "Loaded %d molecule(s), %d error(s) from %s", report.n_loaded, report.n_failed, path.name
    )
    return report


def _record_name(mol: Chem.Mol, path: Path, index: int) -> str:
    """Best display name: the ``_Name`` property if set, else ``stem_index``."""
    if mol.HasProp("_Name"):
        name = mol.GetProp("_Name").strip()
        if name:
            return name
    return f"{path.stem}_{index}"


def _load_sdf(path: Path, progress: ProgressCallback | None) -> LoadReport:
    """Read a multi-molecule SDF file, capturing per-record failures."""
    report = LoadReport(source=path, fmt="sdf")
    supplier = Chem.SDMolSupplier(str(path), sanitize=True, removeHs=True)
    total = len(supplier)

    for i in range(total):
        mol = supplier[i]
        index = i + 1
        if mol is None:
            # RDKit logs the parse/sanitization detail; we record the location.
            report.errors.append(
                LoadError(f"record {index}", "RDKit could not parse or sanitize this record")
            )
        else:
            report.records.append(
                MoleculeRecord(
                    mol=mol,
                    name=_record_name(mol, path, index),
                    source=path,
                    index_in_source=index,
                    properties=mol.GetPropsAsDict(),
                )
            )
        if progress is not None and (index % _PROGRESS_EVERY == 0 or index == total):
            progress(index, total)
    return report


def _load_mol(path: Path) -> LoadReport:
    """Read a single-molecule MOL file."""
    report = LoadReport(source=path, fmt="mol")
    mol = Chem.MolFromMolFile(str(path), sanitize=True, removeHs=True)
    if mol is None:
        report.errors.append(
            LoadError("record 1", "RDKit could not parse or sanitize this MOL file")
        )
    else:
        report.records.append(
            MoleculeRecord(
                mol=mol,
                name=_record_name(mol, path, 1),
                source=path,
                index_in_source=1,
                properties=mol.GetPropsAsDict(),
            )
        )
    return report


def _load_smiles(path: Path, progress: ProgressCallback | None) -> LoadReport:
    """Read a SMILES file: one molecule per line, optional name after whitespace.

    Blank lines and lines starting with ``#`` are skipped. A failing first line
    gets a hint that it may be a header row (common in exported .smi files).
    """
    report = LoadReport(source=path, fmt="smiles")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        smiles = parts[0]
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            message = f"Invalid SMILES {smiles!r}"
            if lineno == 1:
                message += " (is the first line a header row?)"
            report.errors.append(LoadError(f"line {lineno}", message))
        else:
            name = parts[1].strip() if len(parts) > 1 else f"{path.stem}_{lineno}"
            report.records.append(
                MoleculeRecord(
                    mol=mol,
                    name=name,
                    source=path,
                    index_in_source=lineno,
                    properties={},
                )
            )
        if progress is not None and (lineno % _PROGRESS_EVERY == 0 or lineno == total):
            progress(lineno, total)
    return report
