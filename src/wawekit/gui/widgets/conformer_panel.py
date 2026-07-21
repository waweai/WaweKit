"""The Conformers panel: a 3D viewer plus a per-conformer energy table.

Follows the molecule-table selection (like the Structure panel). When the
selected record has conformers, the panel shows the ranked list — conformer id,
force-field energy, energy above the minimum (ΔE), and RMSD to the lowest — and
renders whichever row is chosen in the interactive 3D view. An *Export SDF*
button writes every conformer out with its 3D coordinates.

The panel emits no signals: it is a pure consumer of the selection, and its one
outward action (export) is a self-contained file write. The RDKit-heavy work
already happened in the service; here we only display and serialise it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.conformer_view import ConformerView
from wawekit.models.molecule import MoleculeRecord

logger = logging.getLogger(__name__)

_HEADERS = ("Conf", "Energy (kcal/mol)", "ΔE", "RMSD (Å)")


class ConformerPanel(QWidget):
    """Shows the selected molecule's 3D conformers and their energetics.

    Parameters
    ----------
    dark:
        Initial viewer palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._record: MoleculeRecord | None = None

        self._header = QLabel("", self)
        self._header.setWordWrap(True)

        self._view = ConformerView(dark=dark, parent=self)

        self._table = QTableWidget(0, len(_HEADERS), self)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.setMaximumHeight(190)
        self._table.itemSelectionChanged.connect(self._on_row_changed)

        self._export_button = QPushButton("Export SDF…", self)
        self._export_button.clicked.connect(self._on_export)
        button_row = QHBoxLayout()
        button_row.addWidget(self._export_button)
        button_row.addStretch(1)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._header)
        content_layout.addWidget(self._view, stretch=1)
        content_layout.addWidget(self._table)
        content_layout.addLayout(button_row)

        self._placeholder = QLabel(
            "Select a molecule with conformers.\n"
            "Run Chemistry → Generate Conformers to create them.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

    # ------------------------------------------------------------- public API
    def set_record(self, record: MoleculeRecord | None) -> None:
        """Show ``record``'s conformers, or the placeholder if it has none."""
        self._record = record
        if record is None or record.conformers is None:
            self._stack.setCurrentWidget(self._placeholder)
            self._view.clear()
            return
        self._populate(record)
        self._stack.setCurrentWidget(self._stack.widget(1))

    def set_dark(self, dark: bool) -> None:
        """Match the 3D viewer background to the application theme."""
        self._view.set_dark(dark)

    # ---------------------------------------------------------------- helpers
    def _populate(self, record: MoleculeRecord) -> None:
        """Fill the header and the conformer table for ``record``."""
        conf_set = record.conformers
        lowest = conf_set.lowest
        lowest_energy = lowest.energy if lowest is not None else None

        rng = conf_set.energy_range
        self._header.setText(
            f"<b>{record.name}</b> — {conf_set.n_conformers} conformer(s), "
            f"{conf_set.force_field_used}"
            + (f", ΔE range {rng:.2f} kcal/mol" if rng is not None else "")
        )

        self._table.blockSignals(True)
        self._table.setRowCount(len(conf_set.conformers))
        for row, conformer in enumerate(conf_set.conformers):
            self._set_cell(row, 0, str(conformer.conf_id), conformer.conf_id)
            self._set_cell(row, 1, "—" if conformer.energy is None else f"{conformer.energy:.3f}")
            if conformer.energy is None or lowest_energy is None:
                delta = "—"
            else:
                delta = f"{conformer.energy - lowest_energy:.3f}"
            self._set_cell(row, 2, delta)
            self._set_cell(
                row,
                3,
                "—" if conformer.rms_to_lowest is None else f"{conformer.rms_to_lowest:.3f}",
            )
        self._table.blockSignals(False)

        # Select the lowest-energy conformer (row 0) and show it in 3D.
        if conf_set.conformers:
            self._table.selectRow(0)
            self._show_conformer(conf_set.conformers[0].conf_id)

    def _set_cell(self, row: int, column: int, text: str, conf_id: int | None = None) -> None:
        """Write one table cell, stashing the conformer id on the first column."""
        item = QTableWidgetItem(text)
        if conf_id is not None:
            item.setData(Qt.ItemDataRole.UserRole, conf_id)
        self._table.setItem(row, column, item)

    def _show_conformer(self, conf_id: int) -> None:
        """Render the conformer with id ``conf_id`` in the 3D view."""
        if self._record is not None and self._record.conformers is not None:
            self._view.show_molblock(self._record.conformers.molblock_for(conf_id))

    # --------------------------------------------------------------- handlers
    def _on_row_changed(self) -> None:
        """Show the newly selected conformer in the 3D view."""
        items = self._table.selectedItems()
        if not items:
            return
        conf_id = self._table.item(items[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        if conf_id is not None:
            self._show_conformer(int(conf_id))

    def _on_export(self) -> None:
        """Write every conformer to a chosen SDF file."""
        if self._record is None or self._record.conformers is None:
            return
        from PySide6.QtWidgets import QFileDialog

        safe = "".join(c for c in self._record.name if c.isalnum() or c in "-_ ")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Conformers to SDF", f"{safe or 'conformers'}.sdf", "SDF file (*.sdf)"
        )
        if not filename:
            return
        path = Path(filename).with_suffix(".sdf")
        try:
            path.write_text(self._record.conformers.to_sdf(), encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to export conformers")
            QMessageBox.warning(self, "Export failed", str(exc))
        else:
            logger.info(
                "Exported %d conformer(s) to %s", self._record.conformers.n_conformers, path
            )
