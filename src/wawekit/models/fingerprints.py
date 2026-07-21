"""The fingerprint domain model.

A *fingerprint* encodes a structure as a fixed-length bit vector: each bit means
"some fragment is present". Once molecules are bit vectors, "how similar are
these two?" becomes a fast bitwise operation — which is what makes similarity
search (Module 7) and clustering (Module 11) possible at all.

Why this lives in ``models`` (same fork as Module 5)
----------------------------------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``fingerprint: Fingerprint | None`` field, and ``models`` may never import from
``services``. So the *data* (this module) is a model; the RDKit computation that
fills it lives in :mod:`wawekit.services.chemistry.fingerprints`.

Note this differs from Module 4, where ``StandardizationOptions`` sits in the
service — nothing in ``models`` refers to it. The rule isn't "options go in
services", it's "a model may not depend upward".

Comparability: the reason options are stored *on* the fingerprint
------------------------------------------------------------------
Two fingerprints may only be compared (Tanimoto) if they were built the same
way: Morgan radius 2 and radius 3 vectors are different encodings, and comparing
them yields a number that looks fine and means nothing. Nothing stops that
happening by accident — compute, load more molecules, recompute with a different
radius, and the dataset is quietly mixed.

So every :class:`Fingerprint` carries the (normalized) :class:`FingerprintOptions`
that produced it. Caching then means "reuse only if the parameters match", and
Module 7 can assert a whole dataset is comparable before trusting a similarity.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from rdkit.DataStructs.cDataStructs import ExplicitBitVect

#: MACCS keys are a fixed set of 166 structural patterns. RDKit allocates 167
#: bits because bit 0 is unused padding — hence the odd-looking constant.
MACCS_N_BITS = 167

#: Bit sizes offered for the hashed fingerprints. More bits → fewer collisions
#: (distinct fragments sharing a bit) at the cost of memory.
BIT_SIZE_CHOICES: tuple[int, ...] = (1024, 2048, 4096)


class FingerprintKind(StrEnum):
    """The fingerprint algorithms Wawekit can compute.

    A :class:`~enum.StrEnum` so the value is both a real enum member and a
    plain string — it serializes straight into a settings file (Module 15) or a
    batch config (Module 13) with no conversion.

    Attributes
    ----------
    MORGAN:
        Circular fragments around each atom out to ``radius`` bonds, hashed into
        ``n_bits``. Equivalent to ECFP (radius 2 ≈ ECFP4, since the diameter is
        what ECFP names). The workhorse for similarity.
    MACCS:
        166 predefined structural keys ("has a sulfonamide", "has a 6-ring"...).
        Fixed size, no parameters, and *interpretable* — you can name the bit.
    RDKIT:
        Daylight-style path-based: hashes linear atom paths through the molecule.

    """

    MORGAN = "Morgan"
    MACCS = "MACCS"
    RDKIT = "RDKit"


@dataclass(frozen=True, slots=True)
class FingerprintOptions:
    """How to build a fingerprint — and the identity that makes two comparable.

    Attributes
    ----------
    kind:
        Which algorithm to use.
    radius:
        Morgan only: how many bonds out from each atom to grow fragments.
        2 is the near-universal default (ECFP4).
    n_bits:
        Morgan and RDKit only: length of the hashed bit vector. MACCS ignores
        this — its length is fixed at :data:`MACCS_N_BITS`.
    use_features:
        Morgan only: use pharmacophoric atom types (donor/acceptor/aromatic...)
        instead of exact element identity — this is FCFP rather than ECFP. It
        generalizes across chemotypes, matching an amine to an amine regardless
        of surroundings.

    """

    kind: FingerprintKind = FingerprintKind.MORGAN
    radius: int = 2
    n_bits: int = 2048
    use_features: bool = False

    def normalized(self) -> FingerprintOptions:
        """Return these options with parameters that did not affect the bits zeroed.

        The identity of a fingerprint is only the parameters that actually
        shaped it. MACCS ignores radius, bit size and features entirely, so two
        MACCS fingerprints requested with different radii are *bit-identical*
        and must compare equal — otherwise Module 7 would refuse to compare a
        perfectly comparable dataset, and the cache would recompute for nothing.

        Note the ``==`` comparisons rather than ``is``: ``kind`` may arrive as a
        plain string (from a Qt ``QVariant`` round-trip, or a settings file in
        Module 15), and a :class:`~enum.StrEnum` compares equal to its value
        while failing an identity check. Equality is the safe test here.
        """
        if self.kind == FingerprintKind.MACCS:
            return replace(self, radius=0, n_bits=MACCS_N_BITS, use_features=False)
        if self.kind == FingerprintKind.RDKIT:
            return replace(self, radius=0, use_features=False)
        return self

    @property
    def label(self) -> str:
        """Short human-readable description, e.g. ``Morgan r2 · 2048b``."""
        if self.kind == FingerprintKind.MACCS:
            return "MACCS"
        if self.kind == FingerprintKind.RDKIT:
            return f"RDKit · {self.n_bits}b"
        family = "FCFP" if self.use_features else "Morgan"
        return f"{family} r{self.radius} · {self.n_bits}b"


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """One molecule's bit vector, plus the options that produced it.

    Attributes
    ----------
    bits:
        RDKit's native :class:`ExplicitBitVect`. Kept in native form on purpose:
        it is exactly what ``DataStructs.BulkTanimotoSimilarity`` consumes, so
        Module 7 gets RDKit's C++ speed with no conversion step.
    options:
        The *normalized* options used to build ``bits`` — the comparability key.

    """

    bits: ExplicitBitVect
    options: FingerprintOptions

    @property
    def n_bits(self) -> int:
        """Total length of the bit vector."""
        return self.bits.GetNumBits()

    @property
    def n_on_bits(self) -> int:
        """How many bits are set — a rough structural-complexity signal."""
        return self.bits.GetNumOnBits()

    @property
    def density(self) -> float:
        """Fraction of bits set (0.0–1.0)."""
        return self.n_on_bits / self.n_bits if self.n_bits else 0.0

    @property
    def summary(self) -> str:
        """Compact table-cell text, e.g. ``Morgan · 24 on``."""
        return f"{self.options.kind} · {self.n_on_bits} on"

    def is_comparable_to(self, other: Fingerprint) -> bool:
        """Return True if a similarity between these two would be meaningful."""
        return self.options == other.options
