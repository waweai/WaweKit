"""3D shape and radial-shell descriptor computation.

The first descriptor service that needs *geometry* rather than just the
molecular graph, so it is also the first with a hard prerequisite: a record must
already carry conformers (from
:mod:`wawekit.services.chemistry.conformers`) before it can be measured. Rather
than fail on a dataset that has none, :func:`compute_shape_descriptors` accepts
``generate_missing`` and will produce the geometry itself — the same courtesy
:mod:`wawekit.services.chemistry.similarity` extends by encoding its query with
the dataset's own fingerprint options.

What gets computed
------------------
* **Whole-molecule shape** — straight from RDKit: ``RadiusOfGyration``,
  ``Asphericity``, ``Eccentricity``, ``SpherocityIndex``,
  ``InertialShapeFactor``, ``NPR1``/``NPR2`` and ``PBF``.
* **Radial shells** — this module's own arithmetic: bin atoms by distance from
  the molecule's centre, count :class:`~wawekit.models.shape3d.AtomClass`
  members per bin, normalise.

Design rules (the same seam as every chemistry service before it):

* **Qt-free** — a plain ``progress`` callback; runs in the GUI worker, a CLI, or
  a notebook.
* **A report, not just results** — counts and per-molecule failures come back as
  data.
* **One bad molecule never aborts the run** — it is recorded as a failure and
  keeps ``shape3d = None``.
* **Cache in place** — the result attaches to the record; ``record.mol`` is
  untouched, so the table keeps its objects.

Hydrogens
---------
``include_hydrogens`` governs the **radial** descriptors only. The whole-molecule
shape descriptors are always computed over the full hydrogen-bearing geometry,
which is both RDKit's convention and the only way the published values are
comparable — a radius of gyration measured on a heavy-atom skeleton is a
different quantity, not a variant of the same one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from rdkit import Chem
from rdkit.Chem import Descriptors3D, rdMolDescriptors

from wawekit.models.conformers import ConformerOptions, ConformerSet
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.shape3d import (
    ELECTRONEGATIVE_ELEMENTS,
    AtomClass,
    CenterMode,
    ConformerChoice,
    RadialOptions,
    ShapeDescriptors,
    ShellNormalization,
)
from wawekit.services.io.molecule_loader import ProgressCallback

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Shape3DReport:
    """Outcome of a 3D shape-descriptor run.

    Attributes
    ----------
    records:
        The records the run covered (descriptors cached on them in place).
    computed:
        How many molecules were measured this run.
    reused:
        How many already had a cached set and were skipped.
    conformers_generated:
        How many molecules needed geometry generated first (only non-zero when
        ``generate_missing`` was supplied).
    failures:
        ``"name: message"`` for each molecule that could not be measured — most
        commonly one with no conformers.

    """

    records: list[MoleculeRecord] = field(default_factory=list)
    computed: int = 0
    reused: int = 0
    conformers_generated: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def n_records(self) -> int:
        """Number of records covered by the run."""
        return len(self.records)

    @property
    def n_failed(self) -> int:
        """Number of molecules whose shape descriptors could not be computed."""
        return len(self.failures)


def _atom_class_masks(
    mol: Chem.Mol, selected: np.ndarray
) -> tuple[dict[AtomClass, np.ndarray], np.ndarray]:
    """Return per-class boolean masks plus a carbon mask, over selected atoms.

    All masks are aligned to ``mol``'s atom order and already ANDed with
    ``selected``, so a caller only has to combine them with a distance mask.
    """
    atoms = list(mol.GetAtoms())
    symbols = np.array([atom.GetSymbol() for atom in atoms])
    is_carbon = (symbols == "C") & selected

    is_sp3 = (
        np.array([atom.GetHybridization() == Chem.HybridizationType.SP3 for atom in atoms])
        & is_carbon
    )
    is_aromatic = np.array([atom.GetIsAromatic() for atom in atoms]) & is_carbon
    is_electronegative = np.isin(symbols, list(ELECTRONEGATIVE_ELEMENTS)) & selected

    return {
        AtomClass.SP3_CARBON: is_sp3,
        AtomClass.AROMATIC_CARBON: is_aromatic,
        AtomClass.ELECTRONEGATIVE: is_electronegative,
    }, is_carbon


def compute_radial_shells(
    mol_3d: Chem.Mol, conf_id: int, options: RadialOptions
) -> tuple[tuple[float, float, float], dict[str, float]]:
    """Measure one conformer's radial shell composition.

    Parameters
    ----------
    mol_3d:
        A molecule carrying 3D coordinates (normally
        :attr:`~wawekit.models.conformers.ConformerSet.mol_3d`).
    conf_id:
        Which conformer of ``mol_3d`` to measure.
    options:
        Shell radii, centre definition, normalisation and hydrogen handling.

    Returns
    -------
    tuple
        ``((x, y, z), {key: value})`` — the centre the shells were measured
        from, and the descriptor values keyed by
        :meth:`~wawekit.models.shape3d.RadialOptions.key`.

    """
    positions = mol_3d.GetConformer(conf_id).GetPositions()
    atoms = list(mol_3d.GetAtoms())

    if options.include_hydrogens:
        selected = np.ones(len(atoms), dtype=bool)
    else:
        selected = np.array([atom.GetAtomicNum() != 1 for atom in atoms])

    if not selected.any():  # a lone hydrogen molecule, excluded by the filter
        raise ValueError("no atoms remain after the hydrogen filter")

    # The centre is measured over the same atoms that will be counted, so the
    # descriptor is fully determined by the selection rather than half-referring
    # to atoms it then ignores.
    chosen = positions[selected]
    if options.center == CenterMode.CENTRE_OF_MASS:
        masses = np.array([atom.GetMass() for atom in atoms])[selected]
        center = (chosen * masses[:, None]).sum(axis=0) / masses.sum()
    else:
        center = chosen.mean(axis=0)

    distances = np.full(len(atoms), np.inf)
    distances[selected] = np.linalg.norm(chosen - center, axis=1)

    class_masks, is_carbon = _atom_class_masks(mol_3d, selected)

    values: dict[str, float] = {}
    inner = 0.0
    for radius in options.shells:
        if options.cumulative:
            in_shell = distances <= radius
        else:
            in_shell = (distances > inner) & (distances <= radius)
        inner = radius

        if options.normalization == ShellNormalization.PER_CARBON:
            denominator = float((is_carbon & in_shell).sum())
        elif options.normalization == ShellNormalization.PER_ATOM:
            denominator = float((selected & in_shell).sum())
        else:
            denominator = 1.0

        for atom_class, mask in class_masks.items():
            count = float((mask & in_shell).sum())
            # An empty shell has nothing to divide by. Yielding 0.0 rather than
            # NaN keeps the panel usable by PCA/t-SNE without imputation; see
            # the ShapeDescriptors.radial docstring for what that costs.
            values[options.key(radius, atom_class)] = count / denominator if denominator else 0.0

    return (float(center[0]), float(center[1]), float(center[2])), values


def _whole_molecule_shape(mol_3d: Chem.Mol, conf_id: int) -> dict[str, float]:
    """Compute RDKit's whole-molecule shape descriptors for one conformer."""
    return {
        "radius_of_gyration": float(Descriptors3D.RadiusOfGyration(mol_3d, confId=conf_id)),
        "asphericity": float(Descriptors3D.Asphericity(mol_3d, confId=conf_id)),
        "eccentricity": float(Descriptors3D.Eccentricity(mol_3d, confId=conf_id)),
        "spherocity": float(Descriptors3D.SpherocityIndex(mol_3d, confId=conf_id)),
        "inertial_shape_factor": float(Descriptors3D.InertialShapeFactor(mol_3d, confId=conf_id)),
        "npr1": float(rdMolDescriptors.CalcNPR1(mol_3d, confId=conf_id)),
        "npr2": float(rdMolDescriptors.CalcNPR2(mol_3d, confId=conf_id)),
        "pbf": float(rdMolDescriptors.CalcPBF(mol_3d, confId=conf_id)),
    }


def compute_shape_descriptor_set(
    conformer_set: ConformerSet, options: RadialOptions | None = None
) -> ShapeDescriptors:
    """Compute the full 3D descriptor panel for one molecule's conformers.

    Parameters
    ----------
    conformer_set:
        Generated conformers for one molecule.
    options:
        Radial parameters; defaults to :class:`RadialOptions` if omitted.

    Returns
    -------
    ShapeDescriptors
        The panel, tagged with the conformer options its geometry came from.

    Raises
    ------
    ValueError
        If the conformer set is empty.

    """
    options = options or RadialOptions()
    if not conformer_set.conformers:
        raise ValueError("conformer set is empty")

    if options.conformer == ConformerChoice.MEAN:
        conf_ids = [conformer.conf_id for conformer in conformer_set.conformers]
    else:
        lowest = conformer_set.lowest
        assert lowest is not None  # guarded by the emptiness check above
        conf_ids = [lowest.conf_id]

    centers: list[tuple[float, float, float]] = []
    radials: list[dict[str, float]] = []
    shapes: list[dict[str, float]] = []
    for conf_id in conf_ids:
        center, radial = compute_radial_shells(conformer_set.mol_3d, conf_id, options)
        centers.append(center)
        radials.append(radial)
        shapes.append(_whole_molecule_shape(conformer_set.mol_3d, conf_id))

    mean_radial = {
        key: float(np.mean([radial[key] for radial in radials])) for key in options.keys()
    }
    mean_shape = {key: float(np.mean([shape[key] for shape in shapes])) for key in shapes[0]}
    mean_center = tuple(float(value) for value in np.mean(centers, axis=0))

    return ShapeDescriptors(
        radial=mean_radial,
        center=mean_center,  # type: ignore[arg-type]  # np.mean gives exactly 3
        n_conformers=conformer_set.n_conformers,
        conf_id=conf_ids[0] if options.conformer != ConformerChoice.MEAN else None,
        options=options,
        conformer_options=conformer_set.options,
        **mean_shape,
    )


def radial_sensitivity(
    conformer_set: ConformerSet, options: RadialOptions | None = None
) -> dict[str, float]:
    """Measure how far each radial descriptor moves across a molecule's conformers.

    A 3D descriptor is a property of a *geometry*, not of a molecule, so its
    value carries an uncertainty that a single-conformer number silently hides.
    This reports that uncertainty directly: for every descriptor key, the spread
    (max − min) across all conformers in the set.

    A large spread means the descriptor is conformationally labile and any
    single-conformer value — including the one
    :func:`compute_shape_descriptor_set` returns — should not be compared across
    datasets without fixing the generation protocol first.

    Parameters
    ----------
    conformer_set:
        Generated conformers for one molecule. A set with fewer than two
        conformers has no spread to report and yields all-zero values.
    options:
        Radial parameters; defaults to :class:`RadialOptions` if omitted.

    Returns
    -------
    dict
        ``{descriptor key: spread}``, in :meth:`RadialOptions.keys` order.

    """
    options = options or RadialOptions()
    per_conformer = [
        compute_radial_shells(conformer_set.mol_3d, conformer.conf_id, options)[1]
        for conformer in conformer_set.conformers
    ]
    if len(per_conformer) < 2:
        return dict.fromkeys(options.keys(), 0.0)

    return {
        key: float(max(r[key] for r in per_conformer) - min(r[key] for r in per_conformer))
        for key in options.keys()
    }


def compute_shape_descriptors(
    records: list[MoleculeRecord],
    options: RadialOptions | None = None,
    recompute: bool = False,
    progress: ProgressCallback | None = None,
    generate_missing: ConformerOptions | None = None,
) -> Shape3DReport:
    """Compute and cache 3D shape descriptors for every record that lacks them.

    Parameters
    ----------
    records:
        Dataset (or a selection) to process. Each record's ``shape3d`` field is
        filled in place; nothing else about the record is touched.
    options:
        Radial parameters; defaults to :class:`RadialOptions` if omitted.
    recompute:
        If ``True``, recompute even for records that already have a cached set
        (e.g. to apply new shell radii).
    progress:
        Optional ``(done, total)`` callback (safe to pass a signal's ``emit``).
    generate_missing:
        If given, generate conformers with these options for any record that has
        none, instead of recording it as a failure. Off by default, because
        embedding is orders of magnitude slower than measuring and the caller
        should opt into paying that cost.

    Returns
    -------
    Shape3DReport
        Counts plus any per-molecule failures.

    """
    options = options or RadialOptions()
    report = Shape3DReport(records=list(records))
    total = len(records)
    logger.info("Computing 3D shape descriptors for %d record(s): %s", total, options.label)

    for done, record in enumerate(records, start=1):
        if record.shape3d is not None and not recompute:
            report.reused += 1
        else:
            try:
                if record.conformers is None and generate_missing is not None:
                    from wawekit.services.chemistry.conformers import generate_conformer_set

                    record.conformers = generate_conformer_set(record.mol, generate_missing)
                    report.conformers_generated += 1
                if record.conformers is None:
                    raise ValueError("no conformers; generate 3D conformers first")

                record.shape3d = compute_shape_descriptor_set(record.conformers, options)
                report.computed += 1
            except Exception as exc:  # noqa: BLE001 — one bad molecule must not abort the run
                logger.exception("Shape descriptor computation failed for %s", record.name)
                report.failures.append(f"{record.name}: {exc}")
        if progress is not None:
            progress(done, total)

    logger.info(
        "3D shape descriptors complete: %d computed (%d needed geometry), %d reused, "
        "%d failure(s)",
        report.computed,
        report.conformers_generated,
        report.reused,
        report.n_failed,
    )
    return report
