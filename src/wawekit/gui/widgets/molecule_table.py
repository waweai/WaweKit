"""Molecule table using Qt's Model/View architecture.

Qt separates *data* from *presentation*:

* :class:`MoleculeTableModel` (a :class:`QAbstractTableModel`) adapts our list
  of :class:`~wawekit.models.molecule.MoleculeRecord` objects into rows/columns.
  It stores no widgets and paints nothing.
* :class:`~PySide6.QtWidgets.QTableView` paints whatever model it is given.
* :class:`~PySide6.QtWidgets.QSortFilterProxyModel` sits between them and
  re-orders rows for sorting (and, in later modules, filtering) without ever
  touching the underlying data.
* Since Module 3, a :class:`~wawekit.gui.widgets.structure_delegate.StructureDelegate`
  paints 2D depictions inside the *Structure* column, and the panel emits
  :attr:`MoleculeTablePanel.selection_changed` with the selected record so other
  panels (the structure viewer) can follow the selection.

This separation is why the same model can later feed a structure-grid view, a
plot, or an export — and it is how large tools (DataWarrior, KNIME) stay fast
with hundreds of thousands of rows: the view only asks for visible cells.
"""

from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QLabel,
    QLineEdit,
    QMenu,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.icons import get_icon
from wawekit.gui.widgets.molecule_filter import (
    InvalidFilter,
    MoleculeFilterProxyModel,
    ScaffoldFilter,
    SubstructureFilter,
)
from wawekit.gui.widgets.structure_delegate import (
    RECORD_ROLE,
    THUMB_HEIGHT,
    THUMB_WIDTH,
    StructureDelegate,
)
from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation

logger = logging.getLogger(__name__)

#: Leading columns, shown before the descriptor panel.
_LEADING_HEADERS: tuple[str, ...] = ("#", "Structure", "Name", "SMILES", "Formula", "Heavy atoms")

#: Column order for the table: fixed leading columns, the descriptor panel
#: (built from DESCRIPTOR_SPECS so a new descriptor needs no change here), the
#: fingerprint summary, the similarity score, the scaffold, then Source last.
#: Kept as data so adding a column is a small diff.
_HEADERS: tuple[str, ...] = (
    *_LEADING_HEADERS,
    *(spec.label for spec in DESCRIPTOR_SPECS),
    "Fingerprint",
    "Similarity",
    "Scaffold",
    "Cluster",
    "Substructure",
    "Alerts",
    "Source",
)

#: Index of the column painted by the structure delegate.
STRUCTURE_COLUMN = 1

#: Cap for the SMILES column so long strings don't push other columns offscreen.
_SMILES_COLUMN = 3
_SMILES_MAX_WIDTH = 260

#: Cap for the Scaffold column: scaffold SMILES can be long, same reasoning.
_SCAFFOLD_MAX_WIDTH = 260

#: Descriptor panel bounds, then the trailing columns.
_FIRST_DESCRIPTOR_COLUMN = len(_LEADING_HEADERS)
_FINGERPRINT_COLUMN = _FIRST_DESCRIPTOR_COLUMN + len(DESCRIPTOR_SPECS)
SIMILARITY_COLUMN = _FINGERPRINT_COLUMN + 1
SCAFFOLD_COLUMN = SIMILARITY_COLUMN + 1
CLUSTER_COLUMN = SCAFFOLD_COLUMN + 1
SUBSTRUCTURE_COLUMN = CLUSTER_COLUMN + 1
ALERTS_COLUMN = SUBSTRUCTURE_COLUMN + 1
_SOURCE_COLUMN = ALERTS_COLUMN + 1

#: Shown in the Scaffold column for a molecule with no ring system.
_ACYCLIC_CELL = "(acyclic)"

#: Hover text for the fingerprint column (it has no DescriptorSpec of its own).
_FINGERPRINT_TOOLTIP = (
    "Fingerprint algorithm and how many bits are set.\n"
    "Hover a cell for the full parameters. Required for similarity search."
)

#: Hover text for the similarity column.
_SIMILARITY_TOOLTIP = (
    "Similarity to the most recent query molecule (0–1).\n"
    "Blank until a search is run. Hover a cell to see what it was compared against.\n"
    "Filter with a query like 'Sim >= 0.7'."
)

#: Hover text for the scaffold column (it has no DescriptorSpec of its own).
_SCAFFOLD_TOOLTIP = (
    "Bemis–Murcko scaffold (the core ring systems + linkers).\n"
    "Blank until 'Analyze Scaffolds' is run; '(acyclic)' means no ring system.\n"
    "Use the Scaffolds panel to group and filter by shared scaffold."
)

#: Hover text for the cluster column (it has no DescriptorSpec of its own).
_CLUSTER_TOOLTIP = (
    "Cluster id from the most recent clustering run (largest cluster is 0).\n"
    "Blank until 'Cluster Molecules' is run. Sort this column to group members;\n"
    "colour the Chemical Space plot by Cluster to see them on the map."
)

#: Hover text for the substructure column (it has no DescriptorSpec of its own).
_SUBSTRUCTURE_TOOLTIP = (
    "Whether the molecule contains the most recent substructure query.\n"
    "'✓ N' = N matches, '—' = no match, blank = not searched. Matched atoms are\n"
    "highlighted in the thumbnail and the Structure panel."
)

#: Hover text for the alerts column (it has no DescriptorSpec of its own).
_ALERTS_TOOLTIP = (
    "Structural warnings (PAINS, Brenk, NIH catalogs), checked automatically\n"
    "in the background after a load. ⚠️ N = N alerts triggered; hover a cell\n"
    "for details. A blank cell during a large load means the check hasn't\n"
    "reached that molecule yet."
)

#: Shown while the background alerts audit hasn't reached a molecule yet.
_ALERTS_PENDING_TOOLTIP = "Alerts pending — checked automatically in the background."


class MoleculeTableModel(QAbstractTableModel):
    """Adapts a list of :class:`MoleculeRecord` into a Qt table model.

    The model answers the view's questions: how many rows/columns, what to
    display in each cell (``DisplayRole``), what raw value to sort by
    (``UserRole`` — so 100 sorts after 20, not before it), and which record
    backs a cell (``RECORD_ROLE`` — consumed by the structure delegate).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[MoleculeRecord] = []
        # Which scaffold form the Scaffold column shows. A view preference, not a
        # compute one — both forms are cached, so switching is a repaint. The
        # Scaffolds panel drives this so the column and the grouping agree.
        self._scaffold_representation = ScaffoldRepresentation.MURCKO

    # ------------------------------------------------------------ Qt overrides
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        """Return the number of molecule rows (0 under a valid parent: flat table)."""
        return 0 if parent.isValid() else len(self._records)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802,B008
        """Return the fixed column count from the header definition."""
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        """Column titles across the top; descriptor columns explain themselves.

        Descriptor headers carry a ``ToolTipRole`` string (from the spec) so
        hovering "TPSA" tells the user what it means and its Lipinski limit.
        """
        if orientation != Qt.Orientation.Horizontal:
            return super().headerData(section, orientation, role)
        if role == Qt.ItemDataRole.DisplayRole:
            return _HEADERS[section]
        if role == Qt.ItemDataRole.ToolTipRole:
            if self._is_descriptor_column(section):
                return DESCRIPTOR_SPECS[section - _FIRST_DESCRIPTOR_COLUMN].tooltip
            if section == _FINGERPRINT_COLUMN:
                return _FINGERPRINT_TOOLTIP
            if section == SIMILARITY_COLUMN:
                return _SIMILARITY_TOOLTIP
            if section == SCAFFOLD_COLUMN:
                return _SCAFFOLD_TOOLTIP
            if section == CLUSTER_COLUMN:
                return _CLUSTER_TOOLTIP
            if section == SUBSTRUCTURE_COLUMN:
                return _SUBSTRUCTURE_TOOLTIP
        return super().headerData(section, orientation, role)

    @staticmethod
    def _is_descriptor_column(column: int) -> bool:
        """Return True if ``column`` falls inside the descriptor panel."""
        return _FIRST_DESCRIPTOR_COLUMN <= column < _FINGERPRINT_COLUMN

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        """Return display text, raw sort key, or the backing record, per role."""
        if not index.isValid():
            return None
        record = self._records[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(record, index.row(), column)
        if role == Qt.ItemDataRole.UserRole:
            return self._sort_value(record, index.row(), column)
        if role == RECORD_ROLE:
            return record
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._tooltip(record, column)
        if role == Qt.ItemDataRole.FontRole and column == SIMILARITY_COLUMN:
            return self._similarity_font(record)
        return None

    @staticmethod
    def _tooltip(record: MoleculeRecord, column: int) -> str | None:
        """Per-cell hover text for the two columns whose value needs context."""
        if column == _FINGERPRINT_COLUMN:
            # The cell only has room for a summary; the tooltip carries the full
            # parameters, which are what decide whether two rows are comparable.
            if record.fingerprint is None:
                return None
            return f"{record.fingerprint.options.label} · {record.fingerprint.n_bits} bits total"
        if column == SIMILARITY_COLUMN:
            # A similarity is only meaningful against something. The number is
            # in the cell; what it was measured against goes here, so a score
            # can never be read without its context being one hover away.
            return None if record.similarity is None else record.similarity.query.label
        if column == SCAFFOLD_COLUMN:
            # The cell shows one representation; the hover shows both, so the
            # exact/generic distinction is always available without toggling.
            if record.scaffold is None:
                return None
            if not record.scaffold.has_ring_system:
                return "No ring system (acyclic molecule)"
            return (
                f"Murcko:  {record.scaffold.murcko_smiles}\n"
                f"Generic: {record.scaffold.generic_smiles}"
            )
        if column == CLUSTER_COLUMN:
            # The cell shows only the id; the hover carries the run that gives it
            # meaning (method, parameters) and the cluster's size.
            return None if record.cluster is None else record.cluster.tooltip
        if column == SUBSTRUCTURE_COLUMN:
            return None if record.substructure_match is None else record.substructure_match.tooltip
        if column == ALERTS_COLUMN:
            # Never trigger the compute from a hover — same rule as _display_value.
            if not record.alerts_computed:
                return _ALERTS_PENDING_TOOLTIP
            return "\n".join(record.alerts) if record.alerts else "Clean (no alerts detected)"
        return None

    @staticmethod
    def _similarity_font(record: MoleculeRecord) -> QFont | None:
        """Bold the query molecule's own row.

        After sorting, the query sits at the top scoring 1.000 — but so might a
        duplicate, and once the user re-sorts by another column it is lost in
        the list entirely. Marking it means "this row is the thing you asked
        about", which is otherwise genuinely hard to see.
        """
        if record.similarity is None or not record.similarity.is_query_molecule(record.smiles):
            return None
        font = QFont()
        font.setBold(True)
        return font

    # ------------------------------------------------------------- public API
    def append_records(self, records: list[MoleculeRecord]) -> None:
        """Add ``records`` to the end of the table, notifying attached views.

        ``beginInsertRows``/``endInsertRows`` is Qt's transactional protocol:
        views update incrementally instead of rebuilding everything.
        """
        if not records:
            return
        first = len(self._records)
        last = first + len(records) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._records.extend(records)
        self.endInsertRows()
        logger.debug("Appended %d record(s); table now has %d", len(records), last + 1)

    def clear(self) -> None:
        """Remove every record, notifying attached views."""
        self.beginResetModel()
        self._records.clear()
        self.endResetModel()

    def set_records(self, records: list[MoleculeRecord]) -> None:
        """Replace the whole dataset (used after standardization)."""
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()
        logger.debug("Replaced dataset; table now has %d record(s)", len(records))

    def remove_rows(self, rows: list[int]) -> None:
        """Remove the given source-model ``rows``.

        Deleting from the highest row down keeps the remaining indices valid;
        each removal is announced transactionally so views update in place.
        """
        for row in sorted(set(rows), reverse=True):
            if 0 <= row < len(self._records):
                self.beginRemoveRows(QModelIndex(), row, row)
                del self._records[row]
                self.endRemoveRows()

    def record_at(self, row: int) -> MoleculeRecord:
        """Return the record backing ``row`` (source-model coordinates)."""
        return self._records[row]

    def descriptors_updated(self) -> None:
        """Repaint the descriptor columns after values were cached in place.

        :func:`~wawekit.services.chemistry.descriptors.compute_descriptors`
        mutates records rather than replacing them, so the view has no way to
        know the cells changed. Emitting ``dataChanged`` over the descriptor
        block asks it to re-read exactly those columns — no full model reset,
        so scroll position and selection survive.
        """
        self._columns_updated(_FIRST_DESCRIPTOR_COLUMN, _FINGERPRINT_COLUMN - 1)

    def fingerprints_updated(self) -> None:
        """Repaint the fingerprint column after vectors were cached in place."""
        self._columns_updated(_FINGERPRINT_COLUMN, _FINGERPRINT_COLUMN)

    def similarity_updated(self) -> None:
        """Repaint the fingerprint and similarity columns after a search.

        Both, because a search encodes the dataset as a side effect: molecules
        that had no fingerprint (or one built with other options) now do, and
        the fingerprint column would otherwise still show the old story.
        """
        self._columns_updated(_FINGERPRINT_COLUMN, SIMILARITY_COLUMN)

    def scaffolds_updated(self) -> None:
        """Repaint the scaffold column after scaffolds were cached in place."""
        self._columns_updated(SCAFFOLD_COLUMN, SCAFFOLD_COLUMN)

    def clusters_updated(self) -> None:
        """Repaint the cluster column after assignments were cached in place."""
        self._columns_updated(CLUSTER_COLUMN, CLUSTER_COLUMN)

    def alerts_updated(self) -> None:
        """Repaint the alerts column after the background audit filled it in."""
        self._columns_updated(ALERTS_COLUMN, ALERTS_COLUMN)

    def substructure_updated(self) -> None:
        """Repaint after a substructure search.

        Two column bands: the Structure thumbnails (so matched atoms light up)
        and the Substructure result column. The delegate re-renders because its
        cache key now includes the match.
        """
        self._columns_updated(STRUCTURE_COLUMN, STRUCTURE_COLUMN)
        self._columns_updated(SUBSTRUCTURE_COLUMN, SUBSTRUCTURE_COLUMN)

    @property
    def scaffold_representation(self) -> ScaffoldRepresentation:
        """Which scaffold form the Scaffold column currently shows."""
        return self._scaffold_representation

    def set_scaffold_representation(self, representation: ScaffoldRepresentation) -> None:
        """Switch the Scaffold column between exact and generic, and repaint it.

        No recomputation: both forms are already cached on every record, so this
        just changes which one the column reads.
        """
        if representation != self._scaffold_representation:
            self._scaffold_representation = representation
            self.scaffolds_updated()

    def _columns_updated(self, first: int, last: int) -> None:
        """Tell views to re-read columns ``first``–``last`` for every row."""
        if not self._records:
            return
        top_left = self.index(0, first)
        bottom_right = self.index(len(self._records) - 1, last)
        self.dataChanged.emit(top_left, bottom_right)

    @property
    def records(self) -> list[MoleculeRecord]:
        """The records currently in the model (do not mutate directly)."""
        return self._records

    # ---------------------------------------------------------------- helpers
    def _display_value(self, record: MoleculeRecord, row: int, column: int) -> str | None:
        """Return human-readable text for one cell."""
        if MoleculeTableModel._is_descriptor_column(column):
            spec = DESCRIPTOR_SPECS[column - _FIRST_DESCRIPTOR_COLUMN]
            if record.descriptors is None:
                return ""  # blank until descriptors are computed
            return spec.fmt.format(spec.getter(record.descriptors))
        if column == _FINGERPRINT_COLUMN:
            # A 2048-bit vector isn't displayable; show what it is and how dense.
            return "" if record.fingerprint is None else record.fingerprint.summary
        if column == SIMILARITY_COLUMN:
            # Blank means "not searched", which is honest. A 0.000 here would
            # claim we compared this molecule and found nothing in common.
            return "" if record.similarity is None else record.similarity.display
        if column == SCAFFOLD_COLUMN:
            return MoleculeTableModel._scaffold_cell(record, self._scaffold_representation)
        if column == CLUSTER_COLUMN:
            return "" if record.cluster is None else record.cluster.display
        if column == SUBSTRUCTURE_COLUMN:
            return "" if record.substructure_match is None else record.substructure_match.display
        if column == ALERTS_COLUMN:
            # Blank until the background audit reaches this record — reading
            # .alerts here (instead of checking .alerts_computed first) would
            # run FilterCatalog synchronously on the GUI thread during paint.
            if not record.alerts_computed:
                return ""
            return f"⚠️ {len(record.alerts)}" if record.alerts else ""
        match column:
            case 0:
                return str(row + 1)
            case 1:
                return None  # painted by the structure delegate
            case 2:
                return record.name
            case 3:
                return record.smiles
            case 4:
                return record.formula
            case 5:
                return str(record.num_heavy_atoms)
            case _:
                return record.source_name

    @staticmethod
    def _scaffold_cell(record: MoleculeRecord, representation: ScaffoldRepresentation) -> str:
        """Return the Scaffold column text for one record in ``representation``."""
        if record.scaffold is None:
            return ""  # blank until scaffolds are analysed
        if not record.scaffold.has_ring_system:
            return _ACYCLIC_CELL
        return record.scaffold.smiles_for(representation)

    def _sort_value(self, record: MoleculeRecord, row: int, column: int) -> Any:
        """Return the raw sort key (ints stay ints; text sorts case-insensitively)."""
        if MoleculeTableModel._is_descriptor_column(column):
            if record.descriptors is None:
                return None  # uncomputed rows sink below real values when sorting
            spec = DESCRIPTOR_SPECS[column - _FIRST_DESCRIPTOR_COLUMN]
            return spec.getter(record.descriptors)
        if column == _FINGERPRINT_COLUMN:
            # Sort by bit count, not by the summary text: "9 on" must precede
            # "24 on", which is exactly what string sorting would get wrong.
            return None if record.fingerprint is None else record.fingerprint.n_on_bits
        if column == SIMILARITY_COLUMN:
            # The float, not the formatted string — this column exists to be
            # sorted, and ranking is the entire point of a similarity search.
            return None if record.similarity is None else record.similarity.value
        if column == SCAFFOLD_COLUMN:
            # Sort by the scaffold key so identical scaffolds sit together —
            # sorting this column *is* the flat-table way to group by scaffold.
            if record.scaffold is None:
                return None  # uncomputed rows sink below analysed ones
            return record.scaffold.smiles_for(self._scaffold_representation)
        if column == CLUSTER_COLUMN:
            # Sort by the integer id so clusters group together and 10 follows 9.
            return None if record.cluster is None else record.cluster.cluster_id
        if column == SUBSTRUCTURE_COLUMN:
            # Sort by match count so hits rise to the top; unsearched sinks last.
            return (
                None if record.substructure_match is None else record.substructure_match.n_matches
            )
        if column == ALERTS_COLUMN:
            # Pending rows sink below checked ones, same convention as every
            # other lazily-computed column (descriptors, scaffold, cluster).
            return len(record.alerts) if record.alerts_computed else None
        match column:
            case 0 | 1:
                return row  # structure column: keep load order (no natural sort)
            case 2:
                return record.name.lower()
            case 3:
                return record.smiles
            case 4:
                return record.formula
            case 5:
                return record.num_heavy_atoms
            case _:
                return record.source_name.lower()


class MoleculeTablePanel(QWidget):
    """Self-contained widget: table view + sort proxy + model + delegate.

    Bundling the Model/View pieces behind one small API keeps
    :class:`~wawekit.gui.main_window.MainWindow` simple and makes the panel
    reusable (and testable) on its own.
    """

    #: Emitted with the newly selected MoleculeRecord, or None when cleared.
    selection_changed = Signal(object)

    #: Emitted with a MoleculeRecord the user wants to search for similars of.
    #: The panel does not run the search — it has no worker, no progress bar and
    #: no business knowing about services. It reports the *intent* and lets
    #: MainWindow, which owns those things, decide. Same seam as
    #: ``selection_changed``.
    similarity_requested = Signal(object)

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.model = MoleculeTableModel(self)

        # Proxy: sorts by the raw UserRole values our model provides and filters
        # rows through the quick-filter query (substring or numeric comparison).
        self._proxy = MoleculeFilterProxyModel(self)
        self._proxy.setSourceModel(self.model)
        self._proxy.setSortRole(Qt.ItemDataRole.UserRole)

        self._view = QTableView(self)
        self._view.setModel(self._proxy)
        self._view.setSortingEnabled(True)
        # Qt gotcha: enabling sorting applies the header's *default* indicator,
        # which is column 0 DESCENDING — files would display in reverse load
        # order. Establish an explicit ascending initial sort instead.
        self._view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._view.setAlternatingRowColors(True)
        self._view.verticalHeader().setVisible(False)
        self._view.horizontalHeader().setStretchLastSection(True)

        # Structure thumbnails: custom delegate + row height to fit them.
        self._delegate = StructureDelegate(self._view, dark=dark)
        self._view.setItemDelegateForColumn(STRUCTURE_COLUMN, self._delegate)
        self._view.verticalHeader().setDefaultSectionSize(THUMB_HEIGHT + 8)

        # Selection → domain object translation for the rest of the app.
        self._view.selectionModel().currentRowChanged.connect(self._on_current_row_changed)

        # Right-click context menu (copy/remove), the desktop-app staple.
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._show_context_menu)

        # Quick-filter row: a text box plus a live status label. Typing filters
        # the visible rows without touching the data (the proxy hides rows).
        self._filter_edit = QLineEdit(self)
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.setPlaceholderText("Filter — e.g. aspirin, MW < 500, Sim >= 0.7")
        self._filter_edit.textChanged.connect(self._on_filter_changed)

        self._filter_status = QLabel("", self)
        self._filter_status.setObjectName("filterStatus")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._filter_edit)
        layout.addWidget(self._view)
        layout.addWidget(self._filter_status)

    # ------------------------------------------------------------- public API
    def append_records(self, records: list[MoleculeRecord]) -> None:
        """Append records and keep column widths readable."""
        self.model.append_records(records)
        self._fix_column_widths()
        self._update_filter_status()

    def set_records(self, records: list[MoleculeRecord]) -> None:
        """Replace the entire dataset (e.g. after standardization)."""
        self.model.set_records(records)
        self._fix_column_widths()
        self.selection_changed.emit(None)  # old selection no longer exists
        self._update_filter_status()

    def refresh_descriptors(self) -> None:
        """Repaint descriptor columns after values were computed in place.

        Also re-applies the active filter: a query like ``MW < 500`` matched
        nothing while descriptors were absent, and should take effect now.
        """
        self.model.descriptors_updated()
        self._fix_column_widths()
        self._proxy.invalidate()
        self._update_filter_status()

    def refresh_alerts(self) -> None:
        """Repaint the alerts column after the background audit filled it in."""
        self.model.alerts_updated()
        self._fix_column_widths()

    def refresh_fingerprints(self) -> None:
        """Repaint the fingerprint column after vectors were computed in place."""
        self.model.fingerprints_updated()
        self._fix_column_widths()

    def refresh_scaffolds(self) -> None:
        """Repaint the scaffold column after scaffolds were computed in place.

        Also re-applies any active scaffold filter: one selected before analysis
        matched nothing and should take effect now.
        """
        self.model.scaffolds_updated()
        self._fix_column_widths()
        self._proxy.invalidate()
        self._update_filter_status()

    def set_scaffold_representation(self, representation: ScaffoldRepresentation) -> None:
        """Switch the Scaffold column between exact Murcko and generic framework."""
        self.model.set_scaffold_representation(representation)
        self._fix_column_widths()

    def refresh_clusters(self) -> None:
        """Repaint the cluster column after assignments were computed in place."""
        self.model.clusters_updated()
        self._fix_column_widths()

    def refresh_substructure(self) -> None:
        """Repaint thumbnails + the substructure column, and re-apply the filter."""
        self.model.substructure_updated()
        self._fix_column_widths()
        self._proxy.invalidate()
        self._update_filter_status()

    def apply_substructure_filter(self, only_matches: bool) -> None:
        """Show only matching molecules (``True``) or all of them (``False``)."""
        self._proxy.set_substructure_filter(SubstructureFilter() if only_matches else None)
        self._update_filter_status()

    def apply_scaffold_filter(self, scaffold_filter: ScaffoldFilter | None) -> None:
        """Restrict the table to one scaffold's members (or clear with ``None``)."""
        self._proxy.set_scaffold_filter(scaffold_filter)
        self._update_filter_status()

    def apply_property_range_filter(self, ranges: dict[str, tuple[float, float]] | None) -> None:
        """Filter rows by descriptor property ranges (or clear with None)."""
        from wawekit.gui.widgets.molecule_filter import PropertyRangeFilter

        self._proxy.set_property_range_filter(PropertyRangeFilter(ranges) if ranges else None)
        self._update_filter_status()

    def refresh_similarity(self) -> None:
        """Repaint after a search and rank the table by score, best first.

        Sorting here rather than leaving it to the user is the whole point of a
        similarity search: the answer *is* the order. Descending, because "most
        similar" is what was asked for.

        The filter is re-applied too, for the same reason descriptors do it: a
        standing ``Sim >= 0.7`` query matched nothing while no scores existed
        and must take effect now.
        """
        self.model.similarity_updated()
        self._view.sortByColumn(SIMILARITY_COLUMN, Qt.SortOrder.DescendingOrder)
        self._fix_column_widths()
        self._proxy.invalidate()
        self._update_filter_status()
        # Scroll the score into view. The column sits past the whole descriptor
        # panel, so on a normal window it lands off the right edge: without this
        # the user runs a search and sees no visible change. Sorting silently
        # rearranged the rows, which is somehow worse than nothing happening.
        self._view.scrollTo(
            self._proxy.index(0, SIMILARITY_COLUMN),
            QAbstractItemView.ScrollHint.EnsureVisible,
        )

    def _fix_column_widths(self) -> None:
        """Auto-size columns, then pin the structure and cap the wide text ones."""
        self._view.resizeColumnsToContents()
        self._view.setColumnWidth(STRUCTURE_COLUMN, THUMB_WIDTH + 8)
        if self._view.columnWidth(_SMILES_COLUMN) > _SMILES_MAX_WIDTH:
            self._view.setColumnWidth(_SMILES_COLUMN, _SMILES_MAX_WIDTH)
        if self._view.columnWidth(SCAFFOLD_COLUMN) > _SCAFFOLD_MAX_WIDTH:
            self._view.setColumnWidth(SCAFFOLD_COLUMN, _SCAFFOLD_MAX_WIDTH)

    def selected_records(self) -> list[MoleculeRecord]:
        """Return the records behind the currently selected rows (in view order).

        Selection lives in *proxy* coordinates (what the user sees, possibly
        sorted); ``mapToSource`` translates back to our data's row numbers.
        """
        rows = self._view.selectionModel().selectedRows()
        return [self.model.record_at(self._proxy.mapToSource(ix).row()) for ix in rows]

    def select_records(self, records: list[MoleculeRecord]) -> None:
        """Select the rows backing ``records`` (e.g. from a chemical-space lasso).

        Drives the same selection machinery a mouse click would, so the Structure
        and Conformer panels follow. Rows hidden by the quick-filter are skipped.
        """
        wanted = {id(r) for r in records}
        selection = QItemSelection()
        first_index = None
        for source_row in range(self.model.rowCount()):
            if id(self.model.record_at(source_row)) not in wanted:
                continue
            proxy_index = self._proxy.mapFromSource(self.model.index(source_row, 0))
            if not proxy_index.isValid():
                continue  # currently filtered out of view
            row_selection = self._proxy.index(proxy_index.row(), 0)
            last = self._proxy.index(proxy_index.row(), self.model.columnCount() - 1)
            selection.select(row_selection, last)
            if first_index is None:
                first_index = row_selection

        selection_model = self._view.selectionModel()
        selection_model.clearSelection()
        selection_model.select(selection, QItemSelectionModel.SelectionFlag.Select)
        if first_index is not None:
            self._view.scrollTo(first_index, QAbstractItemView.ScrollHint.EnsureVisible)
            # Set the current index so selection_changed fires for the panels.
            selection_model.setCurrentIndex(first_index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def set_dark(self, dark: bool) -> None:
        """Propagate a theme change to the thumbnail delegate and repaint."""
        self._delegate.set_dark(dark)
        self._view.viewport().update()

    @property
    def row_count(self) -> int:
        """Total number of molecules loaded (ignores the quick-filter)."""
        return self.model.rowCount()

    @property
    def visible_row_count(self) -> int:
        """Number of rows currently passing the quick-filter."""
        return self._proxy.rowCount()

    # --------------------------------------------------------------- handlers
    def _on_filter_changed(self, text: str) -> None:
        """Apply the quick-filter query and report the result to the user."""
        self._proxy.set_query(text)
        self._update_filter_status()

    def _update_filter_status(self) -> None:
        """Refresh the label under the table: match count or a parse error."""
        active = self._proxy.active_filter
        total = self.row_count
        if isinstance(active, InvalidFilter):
            self._filter_status.setText(f"⚠ {active.reason}")
            return
        # A scaffold or substructure filter narrows the table just like a text
        # query, so any active channel means we report the visible count.
        narrowed = (
            self._proxy.scaffold_filter is not None or self._proxy.substructure_filter is not None
        )
        if active is None and not narrowed:
            self._filter_status.setText(f"{total} molecule(s)")
            return
        self._filter_status.setText(f"{self.visible_row_count} of {total} shown")

    def _on_current_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Translate the Qt selection into a MoleculeRecord and broadcast it."""
        record: MoleculeRecord | None = None
        if current.isValid():
            record = self.model.record_at(self._proxy.mapToSource(current).row())
        self.selection_changed.emit(record)

    def _selected_source_rows(self) -> list[int]:
        """Return selected rows in source-model coordinates."""
        return [
            self._proxy.mapToSource(ix).row() for ix in self._view.selectionModel().selectedRows()
        ]

    def _show_context_menu(self, pos) -> None:  # noqa: ANN001 — QPoint
        """Show the right-click menu for the current selection."""
        menu = self._build_context_menu()
        if menu is not None:
            menu.exec(self._view.viewport().mapToGlobal(pos))

    def _build_context_menu(self) -> QMenu | None:
        """Assemble the right-click menu, or ``None`` if nothing is selected.

        Kept separate from :meth:`_show_context_menu` because ``exec`` blocks on
        a modal event loop: a test can inspect what the menu *offers* only if
        building it is reachable without showing it.
        """
        selected = self.selected_records()
        if not selected:
            return None
        menu = QMenu(self)

        # Offered only for a single row: "similar to these five molecules" is a
        # different feature (Module 11's clustering), not this one with a vaguer
        # query. An action that silently used just the first of five would be a
        # small lie.
        if len(selected) == 1:
            query = selected[0]
            find_similar = QAction(get_icon("similarity"), "Find &Similar to This…", menu)
            find_similar.triggered.connect(lambda: self.similarity_requested.emit(query))
            menu.addAction(find_similar)
            menu.addSeparator()

        copy_smiles = QAction(f"Copy SMILES ({len(selected)})", menu)
        copy_smiles.triggered.connect(
            lambda: QApplication.clipboard().setText("\n".join(r.smiles for r in selected))
        )
        menu.addAction(copy_smiles)

        copy_names = QAction(f"Copy Name(s) ({len(selected)})", menu)
        copy_names.triggered.connect(
            lambda: QApplication.clipboard().setText("\n".join(r.name for r in selected))
        )
        menu.addAction(copy_names)

        menu.addSeparator()
        remove = QAction(f"Remove Selected ({len(selected)})", menu)
        remove.triggered.connect(self._remove_selected)
        menu.addAction(remove)

        return menu

    def _remove_selected(self) -> None:
        """Delete the selected rows and clear the downstream selection."""
        rows = self._selected_source_rows()
        if rows:
            self.model.remove_rows(rows)
            self.selection_changed.emit(None)
            logger.info("Removed %d row(s) from the molecule table", len(rows))
