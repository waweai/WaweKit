"""The substructure-match domain model.

*Substructure search* asks "which molecules contain this fragment, and where?" —
the query behind library filtering ("show me every sulfonamide") and SAR work
("highlight the pharmacophore"). A query is a **SMARTS** pattern (the query
language, e.g. ``c1ccncc1`` or ``[#6][OX2H]``) or a plain SMILES read as one.

Relational, like similarity and clustering
------------------------------------------
Whether a molecule matches — and which atoms — depends on the *query*, not on the
molecule alone. So, exactly as :class:`~wawekit.models.similarity.SimilarityScore`
carries its query, a :class:`SubstructureHit` carries the
:class:`SubstructureQuery` that produced it. The atom indices it stores drive the
highlighting in the structure views, and are only meaningful against that query.

Why this lives in ``models``
----------------------------
:class:`~wawekit.models.molecule.MoleculeRecord` carries a
``substructure_match: SubstructureHit | None`` field, and ``models`` may never
import from ``services``. So the *data* is a model; the RDKit matching lives in
:mod:`wawekit.services.chemistry.substructure`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubstructureQuery:
    """A substructure query pattern and how to interpret it.

    Attributes
    ----------
    pattern:
        The query text.
    is_smarts:
        ``True`` to parse ``pattern`` as SMARTS (the query language, more
        expressive); ``False`` to parse it as a plain SMILES.

    """

    pattern: str
    is_smarts: bool = True

    @property
    def label(self) -> str:
        """Human-readable description, e.g. ``SMARTS: c1ccncc1``."""
        return f"{'SMARTS' if self.is_smarts else 'SMILES'}: {self.pattern}"


@dataclass(frozen=True, slots=True)
class SubstructureHit:
    """One molecule's result against a substructure query.

    Attributes
    ----------
    query:
        The query this result is for.
    matches:
        One tuple of matched atom indices per distinct match (empty if the
        molecule does not contain the query).

    """

    query: SubstructureQuery
    matches: tuple[tuple[int, ...], ...]

    @property
    def is_match(self) -> bool:
        """Whether the molecule contains the query at least once."""
        return bool(self.matches)

    @property
    def n_matches(self) -> int:
        """How many distinct times the query occurs."""
        return len(self.matches)

    @property
    def atoms(self) -> frozenset[int]:
        """Union of every matched atom index (drives highlighting)."""
        return frozenset(atom for match in self.matches for atom in match)

    @property
    def display(self) -> str:
        """Short table-cell text: ``✓`` / ``✓ N`` for a match, ``—`` for none."""
        if not self.matches:
            return "—"
        return "✓" if self.n_matches == 1 else f"✓ {self.n_matches}"

    @property
    def tooltip(self) -> str:
        """Hover text: the query and the number of matches."""
        if not self.matches:
            return f"No match for {self.query.label}"
        return f"{self.n_matches} match(es) of {self.query.label}"
