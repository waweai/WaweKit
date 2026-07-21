"""The molecule domain model.

:class:`MoleculeRecord` is Wawekit's central data object: an RDKit molecule
plus the identity and provenance information every feature needs (a display
name, which file it came from, its position in that file, and any properties
carried by the source record, e.g. SDF data fields).

Design notes
------------
* **No Qt here.** Models are pure Python + RDKit so they can be unit-tested and
  reused headlessly (CLI, notebooks, batch pipelines).
* **Lazy caching.** Canonical SMILES and molecular formula are computed on
  first access and cached, because GUI views request display values repeatedly
  (every repaint) and recomputing canonical SMILES is not free.
* **Not frozen.** Unlike :class:`~wawekit.core.config.AppConfig`, records cache
  derived values internally, so full immutability is impractical; treat them as
  read-only by convention after creation.
* **Derived data is one field, not many.** Module 5 added descriptors as a
  single ``descriptors: DescriptorSet | None`` slot rather than eight loose
  columns; Module 6 added ``fingerprint`` the same way. Later modules
  (conformers, scaffolds) attach their results identically, so the record gains
  one field per *concept* instead of one per *value*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

from wawekit.models.clustering import ClusterAssignment
from wawekit.models.conformers import ConformerSet
from wawekit.models.descriptors import DescriptorSet
from wawekit.models.fingerprints import Fingerprint
from wawekit.models.scaffold import ScaffoldResult
from wawekit.models.similarity import SimilarityScore
from wawekit.models.substructure import SubstructureHit


@dataclass(slots=True)
class MoleculeRecord:
    """One molecule with its identity, provenance and source properties.

    Attributes
    ----------
    mol:
        The sanitized RDKit molecule object.
    name:
        Human-readable name (SDF ``_Name`` field, SMILES name column, or a
        generated fallback like ``file_3``).
    source:
        Path of the file this molecule was read from (``None`` if created
        in-memory, e.g. by a future sketcher).
    index_in_source:
        1-based position of the record within its source file.
    properties:
        Data fields attached to the source record (e.g. SDF tags such as
        activity values). Values keep the types RDKit inferred.
    descriptors:
        Computed drug-likeness panel, or ``None`` until
        :func:`~wawekit.services.chemistry.descriptors.compute_descriptors`
        has run. This is a *cache of derived values*, in the same category as
        :attr:`smiles` and :attr:`formula` — filling it does not change the
        molecule. Standardization builds new records, whose ``descriptors``
        start as ``None`` again, so stale numbers cannot survive a structural
        edit.
    fingerprint:
        Computed bit vector, or ``None`` until
        :func:`~wawekit.services.chemistry.fingerprints.compute_fingerprints`
        has run. Same cache discipline as ``descriptors``, with one addition:
        the fingerprint carries the options that built it, so a run with
        different parameters replaces it rather than leaving the dataset mixed.
    similarity:
        Score against the most recent similarity search, or ``None`` if this
        record has not been searched (or could not be). Unlike every other
        derived field here, this one is *not* intrinsic to the molecule: it
        only means anything relative to a query, so the
        :class:`~wawekit.models.similarity.SimilarityScore` carries that query
        with it rather than being a bare float.
    scaffold:
        Bemis–Murcko scaffold (exact and generic forms), or ``None`` until
        :func:`~wawekit.services.chemistry.scaffolds.compute_scaffolds` has run.
        Same cache discipline as ``descriptors``: intrinsic to the structure, so
        standardization's new records start with ``None`` again.
    conformers:
        Generated 3D conformers, or ``None`` until
        :func:`~wawekit.services.chemistry.conformers.generate_conformers` has
        run. The 3D geometry lives on
        :attr:`~wawekit.models.conformers.ConformerSet.mol_3d`, a *separate*
        molecule, so ``mol`` stays 2D for the table and Structure panel.
    cluster:
        Cluster membership from the most recent clustering run, or ``None`` if
        this record has not been clustered. Like ``similarity`` and unlike the
        intrinsic caches, it is dataset-relative, so the assignment carries the
        :class:`~wawekit.models.clustering.ClusterRun` that produced it.
    substructure_match:
        Result of the most recent substructure search (matched atoms + query),
        or ``None`` if not searched. Query-relative, so the
        :class:`~wawekit.models.substructure.SubstructureHit` carries its query;
        its matched atoms drive highlighting in the structure views.

    """

    mol: Chem.Mol
    name: str
    source: Path | None = None
    index_in_source: int = 0
    properties: dict[str, Any] = field(default_factory=dict)
    descriptors: DescriptorSet | None = None
    fingerprint: Fingerprint | None = None
    similarity: SimilarityScore | None = None
    scaffold: ScaffoldResult | None = None
    conformers: ConformerSet | None = None
    cluster: ClusterAssignment | None = None
    substructure_match: SubstructureHit | None = None

    # Lazily-computed caches (excluded from __init__ and repr).
    _smiles: str | None = field(default=None, init=False, repr=False)
    _formula: str | None = field(default=None, init=False, repr=False)
    _alerts: list[str] | None = field(default=None, init=False, repr=False)

    @property
    def smiles(self) -> str:
        """Canonical isomeric SMILES for this molecule (computed once)."""
        if self._smiles is None:
            self._smiles = Chem.MolToSmiles(self.mol)
        return self._smiles

    @property
    def formula(self) -> str:
        """Molecular formula, e.g. ``C9H8O4`` (computed once)."""
        if self._formula is None:
            self._formula = rdMolDescriptors.CalcMolFormula(self.mol)
        return self._formula

    @property
    def alerts(self) -> list[str]:
        """Compute structural alerts (PAINS, Brenk, NIH) lazily and cache them.

        Checking a molecule against several hundred SMARTS patterns is not
        free — unlike :attr:`smiles`/:attr:`formula`, this is too slow to
        trigger from a GUI repaint. The GUI never calls this directly for an
        uncomputed record; it checks :attr:`alerts_computed` first and relies
        on a background pass (:func:`~wawekit.services.chemistry.alerts.compute_alerts_for_records`)
        to fill the cache. Direct callers (tests, a CLI, a notebook) can still
        use this property as a simple compute-and-cache call.
        """
        if self._alerts is None:
            from wawekit.services.chemistry.alerts import compute_alerts

            self._alerts = compute_alerts(self.mol)
        return self._alerts

    @property
    def alerts_computed(self) -> bool:
        """Whether :attr:`alerts` has already been computed and cached.

        Lets a caller (the molecule table) check the cache without
        triggering the computation — the check :attr:`alerts` itself cannot
        offer, since reading it *is* the trigger.
        """
        return self._alerts is not None

    def invalidate_alerts(self) -> None:
        """Clear the cached alerts, so the next :attr:`alerts` access recomputes."""
        self._alerts = None

    @property
    def num_heavy_atoms(self) -> int:
        """Number of non-hydrogen atoms."""
        return self.mol.GetNumHeavyAtoms()

    @property
    def source_name(self) -> str:
        """Short display string for the source file (empty if in-memory)."""
        return self.source.name if self.source is not None else ""
