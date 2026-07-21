"""Exporting a dataset to disk.

The loaders (Module 2) turn files into records; this turns records — with
everything computed on them — back into files. Two formats:

* **CSV** — a flat table of identity, descriptors and annotations, for Excel,
  pandas, or a supervisor's inbox. Uncomputed values are simply blank.
* **SDF** — the molecules themselves plus their computed values as SD data
  fields, so the structures survive the round trip (CSV cannot carry geometry).

Kept Qt-free in ``services/io`` so it runs in the batch worker, a CLI, or a
notebook, and so Module 14's report generator can reuse it.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from rdkit import Chem

from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord

logger = logging.getLogger(__name__)

#: Fixed identity columns that lead every CSV export.
_LEADING_COLUMNS = ("Name", "SMILES", "Formula", "HeavyAtoms")

#: Annotation columns that trail the descriptor block.
_TRAILING_COLUMNS = ("Fingerprint", "Cluster", "Scaffold", "Source")


def _scaffold_cell(record: MoleculeRecord) -> str:
    """Return the scaffold text for an export cell (blank/acyclic/SMILES)."""
    if record.scaffold is None:
        return ""
    return record.scaffold.murcko_smiles if record.scaffold.has_ring_system else "(acyclic)"


def _row(record: MoleculeRecord) -> list[str]:
    """Build one CSV row: identity, descriptors (blank if absent), annotations."""
    row: list[str] = [
        record.name,
        record.smiles,
        record.formula,
        str(record.num_heavy_atoms),
    ]
    for spec in DESCRIPTOR_SPECS:
        row.append(spec.fmt.format(spec.getter(record.descriptors)) if record.descriptors else "")
    row.append(record.fingerprint.summary if record.fingerprint else "")
    row.append(str(record.cluster.cluster_id) if record.cluster else "")
    row.append(_scaffold_cell(record))
    row.append(record.source_name)
    return row


def export_csv(records: list[MoleculeRecord], path: Path) -> int:
    """Write ``records`` to a CSV file, returning how many rows were written.

    Columns: identity, the full descriptor panel, then the fingerprint summary,
    cluster id, scaffold and source. Values not yet computed are left blank.
    """
    header = [*_LEADING_COLUMNS, *(spec.label for spec in DESCRIPTOR_SPECS), *_TRAILING_COLUMNS]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for record in records:
            writer.writerow(_row(record))
    logger.info("Exported %d record(s) to %s", len(records), path)
    return len(records)


def export_sdf(records: list[MoleculeRecord], path: Path) -> int:
    """Write ``records`` to an SDF file, returning how many were written.

    Each molecule keeps its source data fields and gains the computed descriptors
    and cluster id as SD tags. Properties are set on a *copy*, never on the
    shared ``record.mol``.
    """
    writer = Chem.SDWriter(str(path))
    try:
        for record in records:
            mol = Chem.Mol(record.mol)  # copy: never mutate the shared record
            mol.SetProp("_Name", record.name)
            for key, value in record.properties.items():
                mol.SetProp(str(key), str(value))
            if record.descriptors is not None:
                for spec in DESCRIPTOR_SPECS:
                    mol.SetProp(spec.label, spec.fmt.format(spec.getter(record.descriptors)))
            if record.cluster is not None:
                mol.SetProp("Cluster", str(record.cluster.cluster_id))
            writer.write(mol)
    finally:
        writer.close()
    logger.info("Exported %d record(s) to %s", len(records), path)
    return len(records)


def export_mol(record: MoleculeRecord, path: Path) -> None:
    """Write a single molecule to a ``.mol`` file.

    Parameters
    ----------
    record:
        The molecule to export.
    path:
        Target file path (will be overwritten if it exists).

    """
    mol = Chem.Mol(record.mol)  # copy: never mutate the shared record
    mol.SetProp("_Name", record.name)
    for key, value in record.properties.items():
        mol.SetProp(str(key), str(value))
    Chem.MolToMolFile(mol, str(path))
    logger.info("Exported 1 molecule to %s", path)


def export_smiles(records: list[MoleculeRecord], path: Path) -> int:
    """Write ``records`` as a SMILES file: one molecule per line with its name.

    Parameters
    ----------
    records:
        The molecules to export.
    path:
        Target file path (will be overwritten if it exists).

    Returns
    -------
    int
        The number of lines written.

    """
    lines: list[str] = []
    for record in records:
        lines.append(f"{record.smiles}\t{record.name}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Exported %d record(s) to %s", len(records), path)
    return len(records)
