"""The scaffold domain model.

A *scaffold* (Bemis–Murcko framework) is a molecule reduced to its ring systems
and the linkers between them, with terminal side chains removed. It answers a
structural question descriptors and fingerprints cannot: *what core skeleton is
this, and which other molecules share it?* Grouping a dataset by scaffold gives
**scaffold diversity** — the medicinal-chemistry measure of how many distinct
cores a library really contains.

Two representations
-------------------
* **Murcko (exact)** — keeps atom and bond types, so a pyridine core and a
  benzene core stay distinct.
* **Generic framework** — every atom becomes carbon and every bond becomes
  single, so molecules that differ only in heteroatoms collapse together. This
  groups more aggressively; it is the "molecular graph" or "cyclic skeleton".

Both are computed together and cached, so the view can switch between them with
no recomputation (the exact/generic choice is a *view* preference, not a compute
parameter — which is why this module, unlike fingerprints, has no options
dialog).

Why this lives in ``models`` and not ``services``
-------------------------------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``scaffold: ScaffoldResult | None`` field, and the layering rule is
``gui -> services -> models -> core``: a model may never import a service. So the
*data* (this module) is a model, while the RDKit *computation* that fills it
lives in :mod:`wawekit.services.chemistry.scaffolds`.

The acyclic edge case
---------------------
A molecule with no rings (ethanol, acetic acid) has **no** scaffold — RDKit
returns an empty molecule. That is represented honestly here as
``has_ring_system=False`` with empty scaffold SMILES, never as a crash or a
fabricated core. Acyclic molecules form their own group when grouping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

#: Grouping label for molecules that have no ring system at all.
ACYCLIC_LABEL = "(acyclic — no ring system)"


class ScaffoldRepresentation(StrEnum):
    """Which scaffold form to display and group by.

    A :class:`~enum.StrEnum` for the same reason as
    :class:`~wawekit.models.fingerprints.FingerprintKind`: it serializes straight
    into a settings file (Module 15) or a batch config (Module 13).

    Attributes
    ----------
    MURCKO:
        The exact Bemis–Murcko scaffold — atom and bond types preserved.
    GENERIC:
        The generic framework — all atoms carbon, all bonds single.

    """

    MURCKO = "Murcko"
    GENERIC = "Generic"

    @property
    def label(self) -> str:
        """Human-readable name for menus and toggles."""
        return "Murcko (exact)" if self == ScaffoldRepresentation.MURCKO else "Generic framework"


@dataclass(frozen=True, slots=True)
class ScaffoldResult:
    """The Bemis–Murcko scaffold of one molecule, in both representations.

    Frozen because a scaffold is a pure function of the structure: if the
    molecule changes, the right move is to recompute, never to edit in place.

    Attributes
    ----------
    murcko_smiles:
        Canonical SMILES of the exact Murcko scaffold, or ``""`` for an acyclic
        molecule.
    generic_smiles:
        Canonical SMILES of the generic (all-carbon, single-bond) framework, or
        ``""`` for an acyclic molecule.
    has_ring_system:
        Whether the molecule has any ring system. ``False`` means acyclic, in
        which case both SMILES are empty.

    """

    murcko_smiles: str
    generic_smiles: str
    has_ring_system: bool

    def smiles_for(self, representation: ScaffoldRepresentation) -> str:
        """Return the scaffold SMILES for ``representation`` (``""`` if acyclic)."""
        # == not `is`: a StrEnum read back from Qt item-data or a TOML string is a
        # plain str that compares equal but fails identity (the Module 6 lesson).
        if representation == ScaffoldRepresentation.GENERIC:
            return self.generic_smiles
        return self.murcko_smiles

    def group_key(self, representation: ScaffoldRepresentation) -> str:
        """Return the key molecules are grouped under for ``representation``.

        Acyclic molecules all share the empty-string key, so they collect into a
        single group rather than scattering.
        """
        return self.smiles_for(representation)
