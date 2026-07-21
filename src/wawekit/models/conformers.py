"""The conformer domain model.

A *conformer* is one 3D shape a molecule can adopt. Real molecules are flexible,
so a single structure has many low-energy conformers; generating and ranking
them is the basis of shape-based screening, docking preparation, and 3D
descriptor work.

Where the 3D geometry lives
---------------------------
This is the first module to produce **3D** structures, and it introduces one new
rule. The 3D coordinates (with explicit hydrogens and multiple conformers) are
stored on :attr:`ConformerSet.mol_3d` — a *separate* molecule — **not** written
back onto :attr:`~wawekit.models.molecule.MoleculeRecord.mol`. Two reasons:

* The 2D table thumbnail and the Structure panel depict ``record.mol``; a
  hydrogen-decorated 3D mol would render as a cluttered mess there.
* A record's identity is its 2D structure; conformers are a *derived* 3D view of
  it, exactly like descriptors are derived numbers. So they attach as one
  ``record.conformers`` field, in the same cache discipline.

Why this lives in ``models`` and not ``services``
-------------------------------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``conformers: ConformerSet | None`` field, and the layering rule is
``gui -> services -> models -> core``. So the *data* (this module) is a model,
while the RDKit *generation* lives in
:mod:`wawekit.services.chemistry.conformers`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from io import StringIO

from rdkit import Chem


class ForceField(StrEnum):
    """Which force field to optimise embedded conformers with.

    A :class:`~enum.StrEnum` for the same reason as the other option enums: it
    serialises straight into settings (Module 15) or a batch config (Module 13).

    Attributes
    ----------
    MMFF94:
        Merck Molecular Force Field — the usual first choice for drug-like
        organics. Requires parameters for every atom; the service falls back to
        UFF when they are missing.
    UFF:
        Universal Force Field — covers the whole periodic table, so it always
        applies, at some accuracy cost.
    NONE:
        Embed only, no optimisation (fastest; energies are unavailable).

    """

    MMFF94 = "MMFF94"
    UFF = "UFF"
    NONE = "None"

    @property
    def label(self) -> str:
        """Human-readable name for the options dialog."""
        return {
            ForceField.MMFF94: "MMFF94 (recommended)",
            ForceField.UFF: "UFF (universal)",
            ForceField.NONE: "None (embed only)",
        }[self]


@dataclass(frozen=True, slots=True)
class ConformerOptions:
    """User-selected conformer-generation parameters.

    Attributes
    ----------
    n_confs:
        How many conformers to embed before pruning.
    force_field:
        Force field for geometry optimisation and energies.
    prune_rms_threshold:
        Conformers within this RMSD (Å) of an existing one are discarded during
        embedding, so the kept set is genuinely distinct shapes.
    random_seed:
        Seed for the embedding, so a run is reproducible.

    """

    n_confs: int = 10
    force_field: ForceField = ForceField.MMFF94
    prune_rms_threshold: float = 0.5
    random_seed: int = 0xC0FFEE

    @property
    def label(self) -> str:
        """Compact one-line description for status messages and the panel."""
        return f"{self.n_confs} confs · {self.force_field} · prune {self.prune_rms_threshold:g} Å"


@dataclass(frozen=True, slots=True)
class Conformer:
    """One generated 3D shape and its energetics.

    Attributes
    ----------
    conf_id:
        RDKit conformer id within :attr:`ConformerSet.mol_3d`.
    energy:
        Force-field energy in kcal/mol, or ``None`` when no optimisation was
        done (``ForceField.NONE``) or it failed.
    rms_to_lowest:
        Best-fit RMSD (Å) to the lowest-energy conformer, or ``None`` for the
        lowest one itself.

    """

    conf_id: int
    energy: float | None
    rms_to_lowest: float | None


@dataclass(slots=True)
class ConformerSet:
    """All conformers generated for one molecule, ranked by energy.

    Attributes
    ----------
    mol_3d:
        The molecule with explicit hydrogens and every embedded conformer. This
        is where the 3D coordinates live; ``record.mol`` is left as-is.
    conformers:
        The conformers, ordered best (lowest energy) first. Unoptimised sets keep
        embedding order.
    options:
        The parameters the run was configured with.
    force_field_used:
        The force field actually applied — may differ from ``options`` when
        MMFF94 lacked parameters and the service fell back to UFF.

    """

    mol_3d: Chem.Mol
    conformers: list[Conformer]
    options: ConformerOptions
    force_field_used: ForceField

    @property
    def n_conformers(self) -> int:
        """Number of conformers kept after pruning."""
        return len(self.conformers)

    @property
    def lowest(self) -> Conformer | None:
        """The lowest-energy conformer (or the first, if unoptimised)."""
        return self.conformers[0] if self.conformers else None

    @property
    def energy_range(self) -> float | None:
        """Spread between highest and lowest conformer energy (kcal/mol).

        ``None`` when energies are unavailable (embed-only runs).
        """
        energies = [c.energy for c in self.conformers if c.energy is not None]
        if len(energies) < 2:
            return None
        return max(energies) - min(energies)

    def molblock_for(self, conf_id: int) -> str:
        """Return the MDL mol block for one conformer (fed to the 3D viewer)."""
        return Chem.MolToMolBlock(self.mol_3d, confId=conf_id)

    def to_sdf(self) -> str:
        """Serialise every conformer to a multi-record SDF string (for export)."""
        buffer = StringIO()
        writer = Chem.SDWriter(buffer)
        try:
            for conformer in self.conformers:
                writer.write(self.mol_3d, confId=conformer.conf_id)
        finally:
            writer.close()
        return buffer.getvalue()
