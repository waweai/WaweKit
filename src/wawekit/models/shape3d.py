"""The 3D shape-descriptor domain model.

Every descriptor Wawekit computed before this module was **2D**: a function of
the molecular graph alone, identical for every conformer. This module adds the
first family that depends on *geometry* — where the atoms actually sit in space.

Two kinds of number live here, and the distinction matters:

* **Whole-molecule shape descriptors** — radius of gyration, asphericity, the
  principal-moment ratios (NPR1/NPR2), plane-of-best-fit. These summarise the
  overall shape of one conformer, and RDKit computes them directly.
* **Radial shell descriptors** — the composition of concentric shells measured
  outward from the molecule's centre. Rather than asking "how big is it", these
  ask *"what kind of chemistry sits near the core, and what sits at the rim"* —
  an sp3-rich core with a polar rim is a different molecule from the reverse,
  even at identical size. They are built by binning atoms by their distance from
  the centre and counting atom classes per bin.

The naming convention (``r3_sp3C_C`` — sp3 carbons within 3 Å, per carbon in
that same shell) follows the published radial-binning literature so values are
directly comparable with it.

Conformer dependence — read this before comparing numbers
---------------------------------------------------------
Unlike a 2D descriptor, **every value here is a property of one conformer, not
of the molecule.** Change the embedding seed, the force field, or which
conformer you select, and the numbers move. That makes the generation protocol
part of the result: two datasets whose 3D descriptors were computed under
different conformer protocols are not comparable, however similar the columns
look. :class:`ShapeDescriptors` therefore records the
:class:`~wawekit.models.conformers.ConformerOptions` its geometry came from, and
:func:`~wawekit.services.chemistry.shape3d.radial_sensitivity` measures how far
the values actually move across a molecule's own conformers — the same question
:mod:`wawekit.services.reproducibility` asks of standardization protocols, one
dimension over.

Why this lives in ``models`` and not ``services``
-------------------------------------------------
Same rule as :mod:`wawekit.models.conformers`: the *data* is a model, the RDKit
*computation* is a service. ``gui -> services -> models -> core``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from wawekit.models.conformers import ConformerOptions

#: Elements counted as electronegative by :attr:`AtomClass.ELECTRONEGATIVE`.
#: The usual organic-chemistry set: the halogens plus N, O and S.
ELECTRONEGATIVE_ELEMENTS: frozenset[str] = frozenset({"N", "O", "F", "S", "Cl", "Br", "I"})

#: Vertices of the principal-moment-of-inertia triangle, as ``(NPR1, NPR2)``.
#: Every molecule's ``(npr1, npr2)`` falls inside the triangle these define;
#: :attr:`ShapeDescriptors.shape_class` reports the nearest corner.
_PMI_VERTICES: dict[str, tuple[float, float]] = {
    "rod": (0.0, 1.0),
    "disc": (0.5, 0.5),
    "sphere": (1.0, 1.0),
}


class AtomClass(StrEnum):
    """An atom category counted within a radial shell.

    Attributes
    ----------
    SP3_CARBON:
        Saturated (sp3-hybridised) carbon — the ``Fsp3``-style "three
        dimensionality" signal, associated with better solubility and clinical
        success rates.
    AROMATIC_CARBON:
        Carbon in an aromatic ring — flat, stacking-capable surface.
    ELECTRONEGATIVE:
        Any atom in :data:`ELECTRONEGATIVE_ELEMENTS` — a proxy for where a
        molecule's polarity and hydrogen-bonding capacity sit.

    """

    SP3_CARBON = "sp3C"
    AROMATIC_CARBON = "aroC"
    ELECTRONEGATIVE = "electronegative"


class CenterMode(StrEnum):
    """Which point radial distances are measured from.

    Attributes
    ----------
    CENTRE_OF_MASS:
        Mass-weighted centre — heavy atoms pull it toward themselves, so the
        origin tracks where the molecular *substance* is.
    CENTROID:
        Unweighted mean position — every atom counts equally, so the origin
        tracks the molecular *volume* instead.

    """

    CENTRE_OF_MASS = "Centre of mass"
    CENTROID = "Geometric centroid"

    @property
    def label(self) -> str:
        """Human-readable name for the options dialog."""
        return {
            CenterMode.CENTRE_OF_MASS: "Centre of mass (mass-weighted)",
            CenterMode.CENTROID: "Geometric centroid (unweighted)",
        }[self]


class ShellNormalization(StrEnum):
    """What a shell's atom-class count is divided by.

    Raw counts scale with molecular size, so comparing a natural product against
    a fragment on raw counts mostly measures "which is bigger". Normalising
    removes that, which is what makes cross-dataset comparison meaningful.

    Attributes
    ----------
    PER_CARBON:
        Divide by the carbons in the same shell (the published ``_C``
        convention). Reads as "of the carbon skeleton here, what fraction is
        aromatic".
    PER_ATOM:
        Divide by all counted atoms in the same shell — a plain composition
        fraction.
    COUNT:
        No normalisation; the raw atom count.

    """

    PER_CARBON = "per carbon"
    PER_ATOM = "per atom"
    COUNT = "raw count"

    @property
    def suffix(self) -> str:
        """Trailing tag used in descriptor keys (``_C``, ``_A`` or ``_n``)."""
        return {
            ShellNormalization.PER_CARBON: "C",
            ShellNormalization.PER_ATOM: "A",
            ShellNormalization.COUNT: "n",
        }[self]


class ConformerChoice(StrEnum):
    """Which conformer(s) of a molecule the descriptors are taken from.

    Attributes
    ----------
    LOWEST_ENERGY:
        Use the single lowest-energy conformer. Fast, and the conventional
        choice — but it commits the result to one geometry.
    MEAN:
        Average every descriptor across all of the molecule's conformers. More
        robust to a single odd embedding, and pairs naturally with
        :func:`~wawekit.services.chemistry.shape3d.radial_sensitivity`, which
        reports how wide that average's underlying spread was.

    """

    LOWEST_ENERGY = "Lowest energy"
    MEAN = "Mean over conformers"


@dataclass(frozen=True, slots=True)
class RadialOptions:
    """User-selected parameters for radial shell descriptors.

    Frozen and serialisable (every field is a scalar, tuple or
    :class:`~enum.StrEnum`) so it drops straight into a batch config or the
    settings file, exactly like ``FingerprintOptions`` and ``ClusterOptions``.

    Attributes
    ----------
    shells:
        Shell boundary radii in ångström, strictly increasing. The default
        ``(3.0, 6.0)`` matches the published two-shell convention.
    center:
        Which point distances are measured from.
    normalization:
        What each atom-class count is divided by.
    include_hydrogens:
        Whether hydrogens participate in binning and counting. Off by default:
        heavy-atom composition is the chemically interesting signal, and
        including hydrogens mostly re-measures saturation.
    cumulative:
        ``True`` counts every atom **within** each radius (nested spheres, the
        published convention). ``False`` counts each shell as an annulus — only
        atoms between the previous radius and this one — which separates core
        composition from rim composition instead of mixing them.
    conformer:
        Which conformer(s) to measure.

    Raises
    ------
    ValueError
        If ``shells`` is empty, contains a non-positive radius, or is not
        strictly increasing.

    """

    shells: tuple[float, ...] = (3.0, 6.0)
    center: CenterMode = CenterMode.CENTRE_OF_MASS
    normalization: ShellNormalization = ShellNormalization.PER_CARBON
    include_hydrogens: bool = False
    cumulative: bool = True
    conformer: ConformerChoice = ConformerChoice.LOWEST_ENERGY

    def __post_init__(self) -> None:
        """Reject shell radii that cannot describe nested/adjacent shells."""
        if not self.shells:
            raise ValueError("at least one shell radius is required")
        if any(radius <= 0 for radius in self.shells):
            raise ValueError("shell radii must be positive")
        if list(self.shells) != sorted(set(self.shells)):
            raise ValueError("shell radii must be strictly increasing")

    @property
    def label(self) -> str:
        """Compact one-line description for status messages and reports."""
        shells = "/".join(f"{radius:g}" for radius in self.shells)
        mode = "cumulative" if self.cumulative else "annuli"
        return f"{shells} Å {mode} · {self.center} · {self.normalization}"

    def key(self, radius: float, atom_class: AtomClass) -> str:
        """Return the descriptor key for one shell/class pair.

        Examples
        --------
        ``r3_sp3C_C`` — sp3 carbons within 3 Å, per carbon in that shell.

        """
        return f"r{radius:g}_{atom_class}_{self.normalization.suffix}"

    def keys(self) -> list[str]:
        """Every descriptor key this option set produces, in a stable order."""
        return [self.key(radius, cls) for radius in self.shells for cls in AtomClass]


@dataclass(frozen=True, slots=True)
class ShapeDescriptors:
    """The 3D descriptor panel for one molecule, from one conformer protocol.

    Frozen for the same reason as
    :class:`~wawekit.models.descriptors.DescriptorSet`: these values are a pure
    function of a geometry plus its options. If either changes, the right move
    is to compute a new set, never to edit one in place.

    Attributes
    ----------
    radial:
        Shell descriptors keyed by :meth:`RadialOptions.key`, e.g.
        ``{"r3_sp3C_C": 1.0, ...}``. A shell containing no atoms to divide by
        yields ``0.0`` rather than ``NaN``, so the panel drops straight into
        PCA/t-SNE without imputation — at the cost of not distinguishing "empty
        shell" from "none of this class present".
    center:
        The ``(x, y, z)`` point distances were measured from, in the conformer's
        own coordinate frame. Carried so the 3D viewer can draw the shells
        exactly where they were measured.
    radius_of_gyration:
        Mass-weighted spread of atoms about the centre (Å) — overall size.
    asphericity:
        0 for a perfect sphere, 1 for a line. How far from spherical.
    eccentricity:
        0 for a sphere, 1 for a line — the same idea from the moment ratios.
    spherocity:
        1 for a perfect sphere, 0 for a flat or linear molecule.
    inertial_shape_factor:
        Combines all three principal moments; small for symmetric shapes.
    npr1, npr2:
        Normalised principal moments of inertia (I1/I3 and I2/I3). Together they
        place the molecule in the standard PMI triangle — see
        :attr:`shape_class`.
    pbf:
        Plane of best fit: mean atom distance (Å) from the best-fitting plane.
        Near 0 means genuinely flat; above ~1 Å means substantially 3D.
    conf_id:
        The conformer these values came from, or ``None`` when
        :attr:`ConformerChoice.MEAN` averaged several.
    n_conformers:
        How many conformers the molecule had available when this was computed.
    conformer_options:
        The generation parameters that produced the geometry. Without this the
        numbers are not comparable across datasets — see the module docstring.
    options:
        The radial parameters used.

    """

    radial: dict[str, float]
    center: tuple[float, float, float]
    radius_of_gyration: float
    asphericity: float
    eccentricity: float
    spherocity: float
    inertial_shape_factor: float
    npr1: float
    npr2: float
    pbf: float
    n_conformers: int
    options: RadialOptions
    conf_id: int | None = None
    conformer_options: ConformerOptions | None = None

    @property
    def shape_class(self) -> str:
        """Nearest corner of the PMI triangle: ``"rod"``, ``"disc"`` or ``"sphere"``.

        The classic rod/disc/sphere read of ``(npr1, npr2)``. A convenience for
        table display and filtering — the underlying ratios stay available for
        anything quantitative.
        """
        point = (self.npr1, self.npr2)
        return min(
            _PMI_VERTICES,
            key=lambda name: (
                (point[0] - _PMI_VERTICES[name][0]) ** 2 + (point[1] - _PMI_VERTICES[name][1]) ** 2
            ),
        )

    @property
    def is_flat(self) -> bool:
        """Whether the molecule is essentially planar (PBF below 0.5 Å)."""
        return self.pbf < 0.5


@dataclass(frozen=True, slots=True)
class Shape3DSpec:
    """How one whole-molecule shape descriptor is named, read and displayed.

    The 3D counterpart of
    :class:`~wawekit.models.descriptors.DescriptorSpec`, and it exists for the
    same reason: table headers, cell text, sort keys and tooltips all derive
    from one list, so adding a column is a one-entry diff rather than an edit in
    four files.

    Only the **whole-molecule** descriptors get columns. The radial values
    cannot: how many there are and what they are called depend on
    :class:`RadialOptions`, so a fixed column layout cannot hold them. They are
    shown in the Conformers panel, which knows the options that produced them.

    Attributes
    ----------
    key:
        Short token identifying the descriptor.
    label:
        Column header text.
    getter:
        Pulls the value out of a :class:`ShapeDescriptors`.
    fmt:
        :meth:`str.format` spec for the displayed cell text.
    tooltip:
        Plain-language explanation shown on the column header.

    """

    key: str
    label: str
    getter: Callable[[ShapeDescriptors], float | str]
    fmt: str
    tooltip: str


#: The 3D shape panel, in column order. Deliberately short: four numbers a
#: chemist can read at a glance, not every moment ratio RDKit can produce.
SHAPE3D_SPECS: tuple[Shape3DSpec, ...] = (
    Shape3DSpec(
        key="Shape",
        label="Shape",
        getter=lambda s: s.shape_class,
        fmt="{:s}",
        tooltip=(
            "Rod / disc / sphere — the nearest corner of the principal-moment "
            "triangle.\nA coarse read of overall 3D form; NPR1/NPR2 carry the "
            "precise position."
        ),
    ),
    Shape3DSpec(
        key="PBF",
        label="PBF",
        getter=lambda s: s.pbf,
        fmt="{:.2f}",
        tooltip=(
            "Plane of best fit (Å): mean atom distance from the best-fitting "
            "plane.\nNear 0 is genuinely flat; above ~1 Å is substantially "
            "three-dimensional."
        ),
    ),
    Shape3DSpec(
        key="RadGyr",
        label="RadGyr",
        getter=lambda s: s.radius_of_gyration,
        fmt="{:.2f}",
        tooltip="Radius of gyration (Å) — how far the mass spreads from the centre.",
    ),
    Shape3DSpec(
        key="Asph",
        label="Asph",
        getter=lambda s: s.asphericity,
        fmt="{:.2f}",
        tooltip="Asphericity: 0 for a perfect sphere, 1 for a straight line.",
    ),
)

#: Token → spec, keyed lowercase for case-insensitive lookup.
SHAPE3D_BY_KEY: dict[str, Shape3DSpec] = {spec.key.lower(): spec for spec in SHAPE3D_SPECS}
