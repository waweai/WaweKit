"""The descriptor domain model.

A *descriptor* is a number computed from a structure. :class:`DescriptorSet`
holds the classic drug-likeness panel for one molecule, plus the Lipinski
"Rule of 5" verdict derived from it.

Why this lives in ``models`` and not ``services``
-------------------------------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``descriptors: DescriptorSet | None`` field, and the layering rule is
``gui -> services -> models -> core``: a model may never import from a service.
So the *data* (this module) is a model, while the *RDKit computation* that fills
it lives in :mod:`wawekit.services.chemistry.descriptors`. This split is what
lets a notebook build a ``DescriptorSet`` by hand — or a future SD-file reader
adopt values already present in the file — without dragging RDKit along.

The column registry
-------------------
:data:`DESCRIPTOR_SPECS` is the single source of truth for the descriptor
panel: the table headers, the cell formatting, the sort keys and the
quick-filter's vocabulary all read from it. Adding a descriptor means adding
one :class:`DescriptorSpec` here — no other file needs to learn about it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

#: Lipinski "Rule of 5" thresholds. A molecule violating at most one of these
#: is considered orally bioavailable by the classic heuristic.
LIPINSKI_MAX_MW = 500.0
LIPINSKI_MAX_LOGP = 5.0
LIPINSKI_MAX_HBD = 5
LIPINSKI_MAX_HBA = 10

#: A molecule "passes" the rule while violating no more than this many limits.
LIPINSKI_ALLOWED_VIOLATIONS = 1


@dataclass(frozen=True, slots=True)
class DescriptorSet:
    """The drug-likeness descriptor panel for one molecule.

    Frozen because these values are a pure function of the structure: if the
    molecule changes, the right move is to recompute a new set, never to edit
    one in place.

    Attributes
    ----------
    molecular_weight:
        Average molecular mass in g/mol.
    logp:
        Crippen estimate of the octanol/water partition coefficient — the
        standard lipophilicity proxy for membrane permeability.
    tpsa:
        Topological polar surface area in Å², a permeability/absorption proxy.
    h_bond_donors:
        Hydrogen-bond donor count (Lipinski definition).
    h_bond_acceptors:
        Hydrogen-bond acceptor count (Lipinski definition).
    rotatable_bonds:
        Single non-ring bonds between heavy atoms — a flexibility measure.
    ring_count:
        Number of rings in the smallest set of smallest rings (SSSR).

    """

    molecular_weight: float
    logp: float
    tpsa: float
    h_bond_donors: int
    h_bond_acceptors: int
    rotatable_bonds: int
    ring_count: int

    @property
    def lipinski_violations(self) -> int:
        """Count how many of the four Rule-of-5 thresholds this molecule breaks."""
        return sum(
            (
                self.molecular_weight > LIPINSKI_MAX_MW,
                self.logp > LIPINSKI_MAX_LOGP,
                self.h_bond_donors > LIPINSKI_MAX_HBD,
                self.h_bond_acceptors > LIPINSKI_MAX_HBA,
            )
        )

    @property
    def passes_lipinski(self) -> bool:
        """Return True if at most one Rule-of-5 threshold is broken."""
        return self.lipinski_violations <= LIPINSKI_ALLOWED_VIOLATIONS


@dataclass(frozen=True, slots=True)
class DescriptorSpec:
    """How one descriptor is named, read and displayed.

    Attributes
    ----------
    key:
        Token users type in the quick-filter box (e.g. ``MW``). Matched
        case-insensitively.
    label:
        Column header text.
    getter:
        Pulls this descriptor's value out of a :class:`DescriptorSet`.
    fmt:
        :meth:`str.format` spec for the displayed cell text.
    tooltip:
        Plain-language explanation shown on the column header.

    """

    key: str
    label: str
    getter: Callable[[DescriptorSet], float | int]
    fmt: str
    tooltip: str


#: The descriptor panel, in column order. The single source of truth: table
#: headers, cell text, sort keys and filter tokens are all derived from this.
DESCRIPTOR_SPECS: tuple[DescriptorSpec, ...] = (
    DescriptorSpec(
        key="MW",
        label="MW",
        getter=lambda d: d.molecular_weight,
        fmt="{:.2f}",
        tooltip="Molecular weight (g/mol). Lipinski limit: ≤ 500.",
    ),
    DescriptorSpec(
        key="LogP",
        label="LogP",
        getter=lambda d: d.logp,
        fmt="{:.2f}",
        tooltip="Crippen logP — lipophilicity. Lipinski limit: ≤ 5.",
    ),
    DescriptorSpec(
        key="TPSA",
        label="TPSA",
        getter=lambda d: d.tpsa,
        fmt="{:.1f}",
        tooltip="Topological polar surface area (Å²). Oral absorption favours ≤ 140.",
    ),
    DescriptorSpec(
        key="HBD",
        label="HBD",
        getter=lambda d: d.h_bond_donors,
        fmt="{:d}",
        tooltip="Hydrogen-bond donors. Lipinski limit: ≤ 5.",
    ),
    DescriptorSpec(
        key="HBA",
        label="HBA",
        getter=lambda d: d.h_bond_acceptors,
        fmt="{:d}",
        tooltip="Hydrogen-bond acceptors. Lipinski limit: ≤ 10.",
    ),
    DescriptorSpec(
        key="RotB",
        label="RotB",
        getter=lambda d: d.rotatable_bonds,
        fmt="{:d}",
        tooltip="Rotatable bonds — molecular flexibility.",
    ),
    DescriptorSpec(
        key="Rings",
        label="Rings",
        getter=lambda d: d.ring_count,
        fmt="{:d}",
        tooltip="Ring count (SSSR).",
    ),
    DescriptorSpec(
        key="Lipinski",
        label="Lipinski",
        getter=lambda d: d.lipinski_violations,
        fmt="{:d}",
        tooltip="Number of Rule-of-5 thresholds broken (0–4). ≤ 1 is a pass.",
    ),
)

#: Filter-token → spec, keyed lowercase for case-insensitive lookup.
DESCRIPTOR_BY_KEY: dict[str, DescriptorSpec] = {spec.key.lower(): spec for spec in DESCRIPTOR_SPECS}
