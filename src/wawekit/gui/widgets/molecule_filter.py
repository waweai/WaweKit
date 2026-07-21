"""The quick-filter: a tiny query language over the molecule table.

Qt's built-in :meth:`QSortFilterProxyModel.setFilterRegularExpression` matches
the *display text* of a column, which is enough for "show me rows containing
aspirin" and useless for "show me rows with MW < 500" — a regex cannot compare
numbers. So the proxy below overrides :meth:`filterAcceptsRow` and asks the
record itself, not its rendered text.

Three query forms, decided by :func:`parse_filter`:

``aspirin``      substring match against name and SMILES (case-insensitive)
``MW < 500``     numeric comparison against a descriptor
``Sim >= 0.7``   numeric comparison against the last similarity search's scores

Recognised descriptor tokens come from
:data:`~wawekit.models.descriptors.DESCRIPTOR_SPECS`, so a new descriptor
becomes filterable the moment it is added there. Operators: ``<  <=  >  >=  =
==  !=``.

Why similarity reuses this box (Module 7)
------------------------------------------
A similarity threshold is the obvious thing to put in a search dialog, and most
tools do: "find everything above 0.7". We deliberately didn't. A threshold
chosen *before* you see the scores is a guess — set it too high and you re-run
the whole search to find out, too low and you scroll. The scores land in a
sortable column instead, and the filter you already had narrows them
afterwards, interactively, at whatever cutoff turns out to be interesting.

That is one shared box for "MW < 500" and "Sim >= 0.7", one grammar to learn,
and no threshold field on a dialog. Reuse worth having is reuse that removes a
control, not just code.

Boolean combinators (``MW < 500 and LogP > 2``) are deliberately absent: that
is a real expression parser, and it belongs with substructure search in a later
module. Anything unparseable is reported rather than silently ignored — a
filter that quietly matches nothing is how users lose data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel

from wawekit.gui.widgets.structure_delegate import RECORD_ROLE
from wawekit.models.descriptors import DESCRIPTOR_BY_KEY, DESCRIPTOR_SPECS, DescriptorSpec
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation

logger = logging.getLogger(__name__)

#: ``<token> <operator> <number>``, e.g. "MW<=500" or "LogP > -0.5".
_COMPARISON_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z]+)\s*(?P<op><=|>=|!=|==|<|>|=)\s*(?P<value>-?\d+(?:\.\d+)?)\s*$"
)

#: Same shape but with a missing/──malformed number, used to tell "the user is
#: typing a comparison and got it wrong" apart from "this is a text search".
_PARTIAL_COMPARISON_RE = re.compile(r"^\s*(?P<key>[A-Za-z]+)\s*(?:<=|>=|!=|==|<|>|=)")

#: Filter tokens that mean "the last similarity search's score". Both spellings
#: are accepted because both are what people type.
_SIMILARITY_KEYS = frozenset({"sim", "similarity"})

#: Comparison operator → predicate. ``=`` is accepted as a friendly alias for ``==``.
_OPERATORS = {
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@runtime_checkable
class RecordFilter(Protocol):
    """Anything that can decide whether a record stays visible."""

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if ``record`` should be shown."""
        ...


@dataclass(frozen=True, slots=True)
class TextFilter:
    """Case-insensitive substring match against name and SMILES."""

    text: str

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the query appears in the record's name or SMILES."""
        needle = self.text.lower()
        return needle in record.name.lower() or needle in record.smiles.lower()


@dataclass(frozen=True, slots=True)
class NumericFilter:
    """Numeric comparison against one descriptor of a record."""

    spec: DescriptorSpec
    op: str
    value: float

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the record's descriptor satisfies the comparison.

        Records without computed descriptors are hidden: the honest answer to
        "is MW < 500?" is unknown, and showing unknowns alongside confirmed
        matches would misrepresent the result set.
        """
        if record.descriptors is None:
            return False
        return _OPERATORS[self.op](self.spec.getter(record.descriptors), self.value)


@dataclass(frozen=True, slots=True)
class SimilarityFilter:
    """Numeric comparison against the score from the last similarity search.

    A sibling of :class:`NumericFilter` rather than a
    :class:`~wawekit.models.descriptors.DescriptorSpec` entry, because a
    similarity is not a descriptor: it lives in a different field, it is
    relational rather than intrinsic, and it appears and vanishes with each
    search. Bolting it into ``DESCRIPTOR_SPECS`` would buy a few lines of shared
    plumbing and quietly teach the rest of the app that a score is a property of
    a molecule — which is the one idea this module exists to correct.
    """

    op: str
    value: float

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the record's score satisfies the comparison.

        Unscored records are hidden, matching :class:`NumericFilter`'s rule: the
        honest answer to "is it similar?" for a molecule nobody compared is
        *unknown*, and showing unknowns among confirmed hits misrepresents the
        result set.
        """
        if record.similarity is None:
            return False
        return _OPERATORS[self.op](record.similarity.value, self.value)


@dataclass(frozen=True, slots=True)
class ScaffoldFilter:
    """Keep only molecules whose scaffold matches one chosen in the Scaffolds panel.

    This filter is not typed into the quick-filter box — a scaffold SMILES is
    not something a human writes by hand. It is set by *clicking* a group in the
    scaffold panel, so it lives on its own channel of the proxy and combines
    with whatever text query the box holds (see
    :meth:`MoleculeFilterProxyModel.filterAcceptsRow`). That lets "show me this
    scaffold" and "…with MW < 500" be true at once.
    """

    key: str
    representation: ScaffoldRepresentation

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the record's scaffold key equals this filter's key.

        Records without a computed scaffold are hidden, matching the discipline
        of the numeric filters: the honest answer to "is this that scaffold?"
        for an unanalysed molecule is *unknown*.
        """
        if record.scaffold is None:
            return False
        return record.scaffold.group_key(self.representation) == self.key


@dataclass(frozen=True, slots=True)
class SubstructureFilter:
    """Keep only molecules that matched the most recent substructure search.

    Like :class:`ScaffoldFilter` it is a click/checkbox-driven channel, not
    something typed into the box, and it ANDs with the text query. Records that
    were never searched, or did not match, are hidden.
    """

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the record contains the searched substructure."""
        return record.substructure_match is not None and record.substructure_match.is_match


@dataclass(frozen=True, slots=True)
class InvalidFilter:
    """A query that looks like a comparison but cannot be parsed.

    Matches nothing, and carries a ``reason`` the GUI shows the user.
    """

    reason: str

    def matches(self, record: MoleculeRecord) -> bool:
        """Return False — an unparseable filter shows no rows."""
        return False


def parse_filter(text: str) -> RecordFilter | None:
    """Turn a quick-filter query into a predicate.

    Parameters
    ----------
    text:
        Raw text from the filter box.

    Returns
    -------
    RecordFilter | None
        ``None`` for an empty query (meaning "accept everything"), otherwise a
        :class:`NumericFilter`, :class:`TextFilter` or :class:`InvalidFilter`.

    """
    query = text.strip()
    if not query:
        return None

    match = _COMPARISON_RE.match(query)
    if match is not None:
        key = match["key"].lower()
        if key in _SIMILARITY_KEYS:
            return SimilarityFilter(op=match["op"], value=float(match["value"]))
        spec = DESCRIPTOR_BY_KEY.get(key)
        if spec is None:
            # A word followed by an operator, but not a term we know.
            known = ", ".join([*(s.key for s in DESCRIPTOR_SPECS), "Sim"])
            return InvalidFilter(f"Unknown term {match['key']!r}. Try: {known}")
        return NumericFilter(spec=spec, op=match["op"], value=float(match["value"]))

    if _PARTIAL_COMPARISON_RE.match(query):
        return InvalidFilter("Incomplete comparison — expected something like 'MW < 500'")

    return TextFilter(query)


@dataclass(frozen=True, slots=True)
class PropertyRangeFilter:
    """Keep only molecules whose descriptors lie within active min/max ranges.

    This channel is set dynamically by interacting with the range spinboxes
    in the Property Filters panel.
    """

    ranges: dict[str, tuple[float, float]]  # key.lower() -> (min, max)

    def matches(self, record: MoleculeRecord) -> bool:
        """Return True if the record's descriptors lie within all range filters.

        Records without computed descriptors are hidden (unknown status).
        """
        if record.descriptors is None:
            return False
        for key, (min_val, max_val) in self.ranges.items():
            spec = DESCRIPTOR_BY_KEY.get(key)
            if spec is not None:
                val = spec.getter(record.descriptors)
                if not (min_val <= val <= max_val):
                    return False
        return True


class MoleculeFilterProxyModel(QSortFilterProxyModel):
    """Sorting proxy that also filters rows through a :class:`RecordFilter`.

    The proxy asks the source model for the :class:`MoleculeRecord` behind each
    row (via ``RECORD_ROLE``) and hands it to the active filter. Filtering
    therefore sees real typed values — floats, ints — not the strings the table
    happens to be painting.
    """

    def __init__(self, parent=None) -> None:  # noqa: ANN001 — QObject
        super().__init__(parent)
        # Independent channels, combined with AND: the text box the user types
        # into, the scaffold chosen in the Scaffolds panel, the substructure
        # search's "matches only" toggle, and the descriptor property range sliders.
        self._filter: RecordFilter | None = None
        self._scaffold_filter: ScaffoldFilter | None = None
        self._substructure_filter: SubstructureFilter | None = None
        self._property_range_filter: PropertyRangeFilter | None = None

    # ------------------------------------------------------------- public API
    def set_query(self, text: str) -> RecordFilter | None:
        """Parse ``text``, apply it, and return the resulting filter.

        ``invalidate`` tells the view to re-run :meth:`filterAcceptsRow` for
        every row; without it the table would keep showing the previous result.
        (The narrower ``invalidateRowsFilter`` would do, but PySide6 6.11 flags
        it as deprecated, so we use the stable public slot.)
        """
        self._filter = parse_filter(text)
        self.invalidate()
        logger.debug("Quick-filter set to %r → %r", text, self._filter)
        return self._filter

    def set_scaffold_filter(self, scaffold_filter: ScaffoldFilter | None) -> None:
        """Restrict rows to one scaffold (or clear the restriction with ``None``).

        Independent of the text query: both must pass for a row to show.
        """
        self._scaffold_filter = scaffold_filter
        self.invalidate()
        logger.debug("Scaffold filter set to %r", scaffold_filter)

    def set_substructure_filter(self, substructure_filter: SubstructureFilter | None) -> None:
        """Restrict rows to substructure matches (or clear with ``None``)."""
        self._substructure_filter = substructure_filter
        self.invalidate()
        logger.debug("Substructure filter set to %r", substructure_filter)

    def set_property_range_filter(self, range_filter: PropertyRangeFilter | None) -> None:
        """Restrict rows to descriptor property ranges (or clear with ``None``)."""
        self._property_range_filter = range_filter
        self.invalidate()
        logger.debug("Property range filter set to %r", range_filter)

    @property
    def active_filter(self) -> RecordFilter | None:
        """The text filter currently applied (``None`` when the box is empty)."""
        return self._filter

    @property
    def scaffold_filter(self) -> ScaffoldFilter | None:
        """The scaffold restriction currently applied (``None`` when off)."""
        return self._scaffold_filter

    @property
    def substructure_filter(self) -> SubstructureFilter | None:
        """The substructure restriction currently applied (``None`` when off)."""
        return self._substructure_filter

    @property
    def property_range_filter(self) -> PropertyRangeFilter | None:
        """The descriptor property range restriction currently applied."""
        return self._property_range_filter

    def _active_channels(self) -> tuple[RecordFilter, ...]:
        """Return every filter channel that is currently switched on."""
        return tuple(
            f
            for f in (
                self._filter,
                self._scaffold_filter,
                self._substructure_filter,
                self._property_range_filter,
            )
            if f is not None
        )

    # ------------------------------------------------------------ Qt override
    def filterAcceptsRow(  # noqa: N802 — Qt interface
        self, source_row: int, source_parent: QModelIndex
    ) -> bool:
        """Return True if the record behind ``source_row`` passes *every* channel."""
        channels = self._active_channels()
        if not channels:
            return True
        model = self.sourceModel()
        if model is None:
            return True
        record = model.index(source_row, 0, source_parent).data(RECORD_ROLE)
        if not isinstance(record, MoleculeRecord):
            return True
        return all(channel.matches(record) for channel in channels)
