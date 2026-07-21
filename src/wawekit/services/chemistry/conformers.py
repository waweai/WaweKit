"""3D conformer generation.

Turns a 2D (or flat) molecule into a ranked set of 3D shapes:

1. **Add hydrogens** — 3D geometry is meaningless without them.
2. **Embed** with RDKit's **ETKDGv3** distance-geometry method
   (``EmbedMultipleConfs``), which uses knowledge of preferred torsions to
   produce realistic starting geometries, pruning near-duplicates on the fly.
3. **Optimise** each conformer with a force field (**MMFF94**, falling back to
   **UFF** when MMFF lacks parameters for an atom) to get energies.
4. **Rank** by energy and record each conformer's RMSD to the lowest-energy one.

Design rules (the shared seam, now on its sixth module):

* **Qt-free** — a plain ``progress`` callback; runs in the GUI worker, a CLI, or
  a notebook.
* **A report, not just results** — counts and per-molecule failures come back as
  data.
* **One bad molecule never aborts the run** — a molecule that fails to embed is
  recorded as a failure and keeps ``conformers = None``.
* **Cache in place** — like descriptors/scaffolds, the result attaches to the
  record; nothing about ``record.mol`` changes, so the table keeps its objects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rdkit import Chem
from rdkit.Chem import AllChem, rdMolAlign

from wawekit.models.conformers import Conformer, ConformerOptions, ConformerSet, ForceField
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConformerReport:
    """Outcome of a conformer-generation run.

    Attributes
    ----------
    records:
        The records the run covered (conformers cached on them in place).
    computed:
        How many molecules had conformers generated this run.
    reused:
        How many already had conformers and were skipped.
    total_conformers:
        Sum of conformers kept across all molecules processed this run.
    failures:
        ``"name: message"`` for each molecule that could not be embedded.

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    computed: int = 0
    reused: int = 0
    total_conformers: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records covered by the run."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of molecules whose conformers could not be generated."""
        return len(self.failures)


def _optimise(
    mol_h: Chem.Mol, force_field: ForceField
) -> tuple[dict[int, float | None], ForceField]:
    """Optimise every conformer and return ``{conf_id: energy}`` and the FF used.

    MMFF94 is tried first when requested, but it needs parameters for every atom;
    when they are missing RDKit cannot use it, so we fall back to UFF (which
    covers the whole periodic table) rather than failing the molecule.
    """
    conf_ids = [conf.GetId() for conf in mol_h.GetConformers()]

    if force_field == ForceField.NONE:
        return {cid: None for cid in conf_ids}, ForceField.NONE

    used = force_field
    if force_field == ForceField.MMFF94 and not AllChem.MMFFHasAllMoleculeParams(mol_h):
        logger.debug("MMFF params incomplete; falling back to UFF")
        used = ForceField.UFF

    if used == ForceField.MMFF94:
        results = AllChem.MMFFOptimizeMoleculeConfs(mol_h)
    else:
        results = AllChem.UFFOptimizeMoleculeConfs(mol_h)

    # results are (not_converged, energy) per conformer, in conformer order.
    energies = {
        cid: float(energy) for cid, (_converged, energy) in zip(conf_ids, results, strict=False)
    }
    return energies, used


def generate_conformer_set(mol: Chem.Mol, options: ConformerOptions) -> ConformerSet:
    """Generate, optimise and rank conformers for one molecule.

    Parameters
    ----------
    mol:
        A sanitized RDKit molecule (2D or coordinate-less is fine).
    options:
        Generation parameters.

    Returns
    -------
    ConformerSet
        The 3D molecule plus its ranked conformers.

    Raises
    ------
    ValueError
        If embedding produced no conformers (some heavily constrained molecules
        cannot be embedded).

    """
    mol_h = Chem.AddHs(mol)

    params = AllChem.ETKDGv3()
    params.randomSeed = options.random_seed
    params.pruneRmsThresh = options.prune_rms_threshold
    conf_ids = list(AllChem.EmbedMultipleConfs(mol_h, numConfs=options.n_confs, params=params))
    if not conf_ids:
        raise ValueError("embedding produced no conformers")

    energies, used = _optimise(mol_h, options.force_field)

    # Rank: lowest energy first. Unoptimised (None) sets keep embedding order.
    if used == ForceField.NONE:
        ordered_ids = conf_ids
        lowest_id = conf_ids[0]
    else:
        ordered_ids = sorted(conf_ids, key=lambda cid: energies[cid])
        lowest_id = ordered_ids[0]

    conformers: list[Conformer] = []
    for cid in ordered_ids:
        if cid == lowest_id:
            rms: float | None = None  # the reference conformer has no RMSD to itself
        else:
            # GetBestRMS is symmetry-aware; it aligns the probe conformer onto the
            # reference, which also gives the viewer a consistent orientation.
            rms = float(rdMolAlign.GetBestRMS(mol_h, mol_h, prbId=cid, refId=lowest_id))
        conformers.append(Conformer(conf_id=cid, energy=energies[cid], rms_to_lowest=rms))

    return ConformerSet(mol_3d=mol_h, conformers=conformers, options=options, force_field_used=used)


def generate_conformers(
    records: list[MoleculeRecord],
    options: ConformerOptions,
    recompute: bool = False,
    progress: ProgressCallback | None = None,
) -> ConformerReport:
    """Generate and cache conformers for every record that lacks them.

    Parameters
    ----------
    records:
        Dataset (or a selection) to process. Each record's ``conformers`` field
        is filled in place.
    options:
        Generation parameters.
    recompute:
        If ``True``, regenerate even for records that already have conformers
        (e.g. to apply new options).
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).

    Returns
    -------
    ConformerReport
        Counts plus any per-molecule failures.

    """
    report = ConformerReport(records=list(records))
    total = len(records)
    logger.info("Generating conformers for %d record(s): %s", total, options.label)

    for done, record in enumerate(records, start=1):
        if record.conformers is not None and not recompute:
            report.reused += 1
        else:
            try:
                conformer_set = generate_conformer_set(record.mol, options)
                record.conformers = conformer_set
                report.computed += 1
                report.total_conformers += conformer_set.n_conformers
            except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
                logger.exception("Conformer generation failed for %s", record.name)
                report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "Conformers complete: %d computed (%d confs), %d reused, %d failure(s)",
        report.computed,
        report.total_conformers,
        report.reused,
        report.n_failed,
    )
    return report
