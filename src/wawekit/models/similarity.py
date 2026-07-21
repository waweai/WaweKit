"""The similarity domain model.

Module 6 turned every structure into a bit vector. This module answers the
question those vectors exist for: *given this molecule, which others in my
dataset look like it?* That question — "find me more compounds like my hit" —
is the single most-used operation in a medicinal chemist's day.

A similarity is not a property of a molecule
--------------------------------------------
This is the design fork that makes this module different from Modules 5 and 6.

A descriptor (MW) and a fingerprint are *intrinsic*: they depend on the
structure and nothing else. Recompute them tomorrow, get the same answer.
A similarity score is **relational** — 0.62 is meaningless on its own. It is
0.62 *against aspirin*, *by Tanimoto*, *on Morgan r2 · 2048b vectors*. Change
any of those three and the number changes while looking exactly as plausible.

So :class:`SimilarityScore` refuses to be a bare float. It carries the
:class:`SimilarityQuery` that produced it, in exactly the discipline Module 6
established when :class:`~wawekit.models.fingerprints.Fingerprint` started
carrying its options: **a derived number travels with the context that makes it
true.** The table can then say "0.62 vs aspirin" instead of "0.62", and a score
left over from an earlier search can be spotted rather than believed.

Why the query stores SMILES rather than the record
---------------------------------------------------
:class:`SimilarityQuery` identifies the query molecule by canonical SMILES, not
by a reference to the :class:`~wawekit.models.molecule.MoleculeRecord` it came
from. Two reasons, both practical:

* The query may not be *in* the dataset at all — pasting a SMILES to search
  against a library is standard practice, and there is no record to point at.
* Holding a record would keep it alive after the user deletes that row, and
  would make the score's identity depend on object lifetime instead of on
  chemistry.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from wawekit.models.fingerprints import FingerprintOptions


class SimilarityMetric(StrEnum):
    """How to turn two bit vectors into one number.

    All three compare the same three quantities: bits set in *a*, bits set in
    *b*, and bits *c* set in both. They differ only in how generously they
    reward the overlap.

    A :class:`~enum.StrEnum` for the same reason as
    :class:`~wawekit.models.fingerprints.FingerprintKind`: it serializes
    straight into a settings file (Module 15) or a batch config (Module 13).

    Attributes
    ----------
    TANIMOTO:
        ``c / (a + b - c)`` — overlap divided by the union. The field's default
        and the one every published "similarity ≥ 0.85" threshold assumes. If
        you are unsure, this is the answer.
    DICE:
        ``2c / (a + b)`` — counts the overlap twice, so it scores higher than
        Tanimoto for the same pair. Useful when comparing molecules of very
        different sizes, where Tanimoto's union denominator punishes the
        smaller one hard.
    COSINE:
        ``c / sqrt(a * b)`` — the geometric angle between the two vectors.
        Common in chemical-space work and machine learning.

    """

    TANIMOTO = "Tanimoto"
    DICE = "Dice"
    COSINE = "Cosine"


@dataclass(frozen=True, slots=True)
class SimilarityQuery:
    """What a set of scores was measured *against* — the score's context.

    Frozen and value-comparable, so two scores can be checked for "were these
    produced by the same search?" with ``==``.

    Attributes
    ----------
    smiles:
        Canonical SMILES of the query molecule. Identity by chemistry, not by
        object reference — see the module docstring.
    name:
        Display name for the query, shown in the table tooltip and status bar.
    metric:
        Which similarity coefficient was used.
    fingerprint:
        The (normalized) fingerprint options both sides were encoded with.
        Two scores computed with different options are not on the same scale,
        which is precisely why this is part of the identity.

    """

    smiles: str
    name: str
    metric: SimilarityMetric
    fingerprint: FingerprintOptions

    @property
    def label(self) -> str:
        """Full provenance line, e.g. ``Tanimoto vs aspirin · Morgan r2 · 2048b``."""
        return f"{self.metric} vs {self.name} · {self.fingerprint.label}"


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    """One molecule's similarity to a query, inseparable from that query.

    Attributes
    ----------
    value:
        The coefficient, 0.0–1.0. 1.0 means the two fingerprints are identical
        — which is *not* the same as the molecules being identical, since
        hashed fingerprints can collide and stereochemistry is invisible to
        them.
    query:
        The search that produced ``value``.

    """

    value: float
    query: SimilarityQuery

    def is_query_molecule(self, smiles: str) -> bool:
        """Return True if ``smiles`` is the molecule this score was measured against.

        Deliberately *not* ``value == 1.0``. A perfect score means the two
        fingerprints are identical, which is weaker than being the same
        molecule: hashed vectors collide, MACCS keys are coarse enough that
        distinct structures routinely share them, and no fingerprint here sees
        stereochemistry. Comparing canonical SMILES asks the question we
        actually mean, and it correctly flags a duplicate of the query sitting
        elsewhere in the dataset.
        """
        return smiles == self.query.smiles

    @property
    def display(self) -> str:
        """Cell text: three decimals, e.g. ``0.847``.

        Three because published similarity thresholds are quoted to two (0.85),
        and a third digit lets a user see which side of the line a borderline
        compound falls on.
        """
        return f"{self.value:.3f}"
