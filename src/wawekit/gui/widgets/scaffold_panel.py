"""The Scaffolds panel: scaffold diversity as a ranked, clickable list.

Where the molecule table shows one row per *molecule*, this dock shows one row
per *scaffold* — the analytical inversion that gives scaffold analysis its
point. It reports diversity (how many distinct cores the dataset holds), ranks
scaffolds by how many molecules share them, renders each as a thumbnail, and —
when one is clicked — asks the table to filter down to that scaffold's members.

The exact/generic toggle lives here, not in a compute dialog, because both
scaffold forms are already cached on every record: switching between them is a
regroup and a repaint, never a recomputation. The panel owns no worker and no
RDKit computation; it renders results and emits *intent* (which scaffold, which
representation), leaving :class:`~wawekit.gui.main_window.MainWindow` to act —
the same seam every other panel uses.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem, rdBase

from wawekit.models.scaffold import ScaffoldRepresentation
from wawekit.services.chemistry.scaffolds import ScaffoldGroup
from wawekit.services.rendering.mol_renderer import render_svg

logger = logging.getLogger(__name__)

#: Thumbnail size for the scaffold icons in the list.
_THUMB_W = 130
_THUMB_H = 72

#: Cap on how many scaffolds we render as rows. Datasets with thousands of
#: singletons would otherwise render thousands of thumbnails for no insight;
#: the ranked list means the ones past this point are all size-1 anyway.
_MAX_ROWS = 400

#: Item-data role carrying the ScaffoldGroup behind each row.
_GROUP_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ScaffoldPanel(QWidget):
    """Ranked scaffold list with a diversity headline and a representation toggle.

    Parameters
    ----------
    dark:
        Initial thumbnail palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    #: Emitted with the clicked :class:`ScaffoldGroup`, or ``None`` for "show all".
    scaffold_selected = Signal(object)

    #: Emitted with the chosen :class:`ScaffoldRepresentation` when the toggle flips.
    representation_changed = Signal(object)

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = dark
        self._groups: list[ScaffoldGroup] = []
        self._total_records = 0
        self._representation = ScaffoldRepresentation.MURCKO

        # --- representation toggle
        self._murcko_radio = QRadioButton(ScaffoldRepresentation.MURCKO.label, self)
        self._generic_radio = QRadioButton(ScaffoldRepresentation.GENERIC.label, self)
        self._murcko_radio.setChecked(True)
        self._rep_group = QButtonGroup(self)
        self._rep_group.addButton(self._murcko_radio)
        self._rep_group.addButton(self._generic_radio)
        self._murcko_radio.toggled.connect(self._on_representation_toggled)
        rep_row = QHBoxLayout()
        rep_row.addWidget(QLabel("Group by:", self))
        rep_row.addWidget(self._murcko_radio)
        rep_row.addWidget(self._generic_radio)
        rep_row.addStretch(1)

        # --- diversity headline
        self._headline = QLabel("", self)
        self._headline.setObjectName("scaffoldHeadline")
        self._headline.setWordWrap(True)

        # --- show-all (clear filter) button
        self._show_all_button = QPushButton("Show all molecules", self)
        self._show_all_button.setEnabled(False)
        self._show_all_button.clicked.connect(self._on_show_all)

        # --- scaffold list
        self._list = QListWidget(self)
        self._list.setIconSize(QSize(_THUMB_W, _THUMB_H))
        self._list.setUniformItemSizes(False)
        self._list.setWordWrap(True)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)

        # --- placeholder shown before any analysis
        self._placeholder = QLabel(
            "Run Chemistry → Analyze Scaffolds\n" "to group the dataset by its core scaffolds.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._list)

        layout = QVBoxLayout(self)
        layout.addLayout(rep_row)
        layout.addWidget(self._headline)
        layout.addWidget(self._show_all_button)
        layout.addWidget(self._stack, stretch=1)

    # ------------------------------------------------------------- public API
    def set_groups(
        self,
        groups: list[ScaffoldGroup],
        representation: ScaffoldRepresentation,
        total_records: int,
    ) -> None:
        """Display ``groups`` (already ranked) and refresh the diversity headline."""
        self._groups = groups
        self._representation = representation
        self._total_records = total_records
        self._sync_radio_to_representation(representation)
        self._populate()

    def set_dark(self, dark: bool) -> None:
        """Switch the thumbnail palette and re-render the current groups."""
        if dark != self._dark:
            self._dark = dark
            self._populate()

    def clear_selection(self) -> None:
        """Deselect any chosen scaffold without emitting a signal."""
        self._list.blockSignals(True)
        self._list.clearSelection()
        self._list.setCurrentItem(None)
        self._list.blockSignals(False)
        self._show_all_button.setEnabled(False)

    @property
    def representation(self) -> ScaffoldRepresentation:
        """The scaffold representation currently selected in the toggle."""
        return self._representation

    # ---------------------------------------------------------------- render
    def _populate(self) -> None:
        """Rebuild the headline and the scaffold rows from the current groups."""
        if not self._groups:
            self._headline.setText("")
            self._list.clear()
            self._stack.setCurrentWidget(self._placeholder)
            return

        analysed = sum(g.size for g in self._groups)
        distinct = len(self._groups)
        singletons = sum(1 for g in self._groups if g.size == 1)
        self._headline.setText(
            f"<b>{analysed}</b> molecule(s) → <b>{distinct}</b> distinct scaffold(s) "
            f"({singletons} appear once)."
        )

        self._list.blockSignals(True)
        self._list.clear()
        for group in self._groups[:_MAX_ROWS]:
            self._list.addItem(self._make_item(group))
        self._list.blockSignals(False)

        if len(self._groups) > _MAX_ROWS:
            note = QListWidgetItem(f"… and {len(self._groups) - _MAX_ROWS} more (all appear once)")
            note.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(note)

        self._stack.setCurrentWidget(self._list)

    def _make_item(self, group: ScaffoldGroup) -> QListWidgetItem:
        """Build one list row: thumbnail + count + scaffold, carrying the group."""
        item = QListWidgetItem(f"{group.size} molecule(s)\n{group.label}")
        item.setData(_GROUP_ROLE, group)
        icon = self._render_icon(group)
        if icon is not None:
            item.setIcon(icon)
        item.setToolTip(group.label)
        return item

    def _render_icon(self, group: ScaffoldGroup) -> QIcon | None:
        """Render a scaffold's structure as a thumbnail icon (``None`` on failure).

        Acyclic molecules have no scaffold to draw, and a malformed scaffold must
        never crash the panel — either case simply yields no icon.
        """
        if group.is_acyclic:
            return None
        try:
            with rdBase.BlockLogs():
                mol = Chem.MolFromSmiles(group.key)
            if mol is None:
                return None
            svg = render_svg(mol, _THUMB_W, _THUMB_H, dark=self._dark)
        except Exception:  # noqa: BLE001 — a bad depiction must not break the panel
            logger.exception("Failed to render scaffold thumbnail for %r", group.key)
            return None

        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        image = QImage(_THUMB_W, _THUMB_H, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return QIcon(QPixmap.fromImage(image))

    # --------------------------------------------------------------- handlers
    def _on_representation_toggled(self, murcko_checked: bool) -> None:
        """Emit the newly chosen representation when the radio flips."""
        representation = (
            ScaffoldRepresentation.MURCKO if murcko_checked else ScaffoldRepresentation.GENERIC
        )
        if representation != self._representation:
            self._representation = representation
            self.representation_changed.emit(representation)

    def _sync_radio_to_representation(self, representation: ScaffoldRepresentation) -> None:
        """Set the radios to ``representation`` without re-emitting the signal."""
        self._murcko_radio.blockSignals(True)
        self._generic_radio.blockSignals(True)
        self._murcko_radio.setChecked(representation == ScaffoldRepresentation.MURCKO)
        self._generic_radio.setChecked(representation == ScaffoldRepresentation.GENERIC)
        self._murcko_radio.blockSignals(False)
        self._generic_radio.blockSignals(False)

    def _on_selection_changed(self) -> None:
        """Emit the selected scaffold group so the table can filter to it."""
        items = self._list.selectedItems()
        if not items:
            return
        group = items[0].data(_GROUP_ROLE)
        if group is None:  # the "… and N more" note row
            return
        self._show_all_button.setEnabled(True)
        self.scaffold_selected.emit(group)

    def _on_show_all(self) -> None:
        """Clear the scaffold filter and the list selection."""
        self.clear_selection()
        self.scaffold_selected.emit(None)
