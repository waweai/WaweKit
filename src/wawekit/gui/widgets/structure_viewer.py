"""The Structure panel: large 2D depiction + details for one molecule.

Lives in a dock next to the molecule table. Whatever row the user selects is
rendered here as scalable vector graphics (:class:`~PySide6.QtSvgWidgets.QSvgWidget`
— crisp at any panel size), together with the record's identity (name, formula,
canonical SMILES) and its source properties (SDF data fields). Two actions:
copy the SMILES to the clipboard, save the depiction as SVG or PNG.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.rendering.mol_renderer import render_svg

logger = logging.getLogger(__name__)

#: Logical render size for the panel depiction (SVG scales beyond this).
_RENDER_W = 380
_RENDER_H = 300

#: Pixel size used when exporting a PNG (high enough for slides/papers).
_EXPORT_W = 1200
_EXPORT_H = 950


class StructureViewerPanel(QWidget):
    """Shows the currently selected molecule: depiction, identity, properties.

    Parameters
    ----------
    dark:
        Initial depiction palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = dark
        self._record: MoleculeRecord | None = None
        self._svg_text: str = ""

        # --- identity header
        self._name_label = QLabel("", self)
        self._name_label.setStyleSheet("font-weight: bold; font-size: 12pt;")
        self._name_label.setWordWrap(True)
        self._formula_label = QLabel("", self)
        self._alerts_label = QLabel("", self)
        self._alerts_label.setStyleSheet("color: #d9534f; font-weight: bold;")
        self._alerts_label.setWordWrap(True)
        self._alerts_label.setVisible(False)
        self._smiles_label = QLabel("", self)
        self._smiles_label.setWordWrap(True)
        self._smiles_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # --- depiction area: placeholder page <-> SVG page
        self._placeholder = QLabel(
            "Select a molecule in the table\nto see its structure here.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._svg = QSvgWidget(self)
        self._depiction_stack = QStackedWidget(self)
        self._depiction_stack.addWidget(self._placeholder)
        self._depiction_stack.addWidget(self._svg)
        self._depiction_stack.setMinimumHeight(220)

        # --- properties table (SDF data fields)
        self._props = QTableWidget(0, 2, self)
        self._props.setHorizontalHeaderLabels(["Property", "Value"])
        self._props.horizontalHeader().setStretchLastSection(True)
        self._props.verticalHeader().setVisible(False)
        self._props.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # --- actions
        self._copy_button = QPushButton("Copy SMILES", self)
        self._copy_button.clicked.connect(self._on_copy_smiles)
        self._save_button = QPushButton("Save Image…", self)
        self._save_button.clicked.connect(self._on_save_image)
        buttons = QHBoxLayout()
        buttons.addWidget(self._copy_button)
        buttons.addWidget(self._save_button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self._name_label)
        layout.addWidget(self._formula_label)
        layout.addWidget(self._alerts_label)
        layout.addWidget(self._depiction_stack, stretch=3)
        layout.addWidget(self._smiles_label)
        layout.addLayout(buttons)
        layout.addWidget(self._props, stretch=2)

        self._update_ui()

    # ------------------------------------------------------------- public API
    def set_record(self, record: MoleculeRecord | None) -> None:
        """Display ``record`` (or the placeholder when ``None``)."""
        self._record = record
        self._update_ui()

    def set_dark(self, dark: bool) -> None:
        """Switch depiction palette and re-render the current molecule."""
        if dark != self._dark:
            self._dark = dark
            self._update_ui()

    def refresh(self) -> None:
        """Re-render the current molecule (e.g. after a substructure search)."""
        self._update_ui()

    @property
    def record(self) -> MoleculeRecord | None:
        """The record currently displayed (``None`` when showing placeholder)."""
        return self._record

    # ---------------------------------------------------------------- helpers
    def _update_ui(self) -> None:
        """Re-render depiction and refresh labels/properties for the record."""
        record = self._record
        has_record = record is not None
        self._copy_button.setEnabled(has_record)
        self._save_button.setEnabled(has_record)

        if record is None:
            self._name_label.clear()
            self._formula_label.clear()
            self._alerts_label.clear()
            self._alerts_label.setVisible(False)
            self._smiles_label.clear()
            self._props.setRowCount(0)
            self._depiction_stack.setCurrentWidget(self._placeholder)
            return

        self._name_label.setText(record.name)
        self._formula_label.setText(f"{record.formula}   ·   {record.num_heavy_atoms} heavy atoms")
        self._smiles_label.setText(record.smiles)

        if record.alerts:
            self._alerts_label.setText("⚠️ Alerts: " + ", ".join(record.alerts))
            self._alerts_label.setVisible(True)
        else:
            self._alerts_label.clear()
            self._alerts_label.setVisible(False)

        hit = record.substructure_match
        highlight = sorted(hit.atoms) if hit is not None and hit.is_match else None
        try:
            self._svg_text = render_svg(
                record.mol, _RENDER_W, _RENDER_H, dark=self._dark, highlight_atoms=highlight
            )
        except Exception:  # noqa: BLE001 — depiction failure must not break selection
            logger.exception("Failed to render structure for %s", record.name)
            self._placeholder.setText("Could not render this structure\n(see log file).")
            self._depiction_stack.setCurrentWidget(self._placeholder)
        else:
            self._svg.load(QByteArray(self._svg_text.encode("utf-8")))
            self._svg.renderer().setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            self._depiction_stack.setCurrentWidget(self._svg)

        self._props.setRowCount(len(record.properties))
        for row, (key, value) in enumerate(sorted(record.properties.items())):
            self._props.setItem(row, 0, QTableWidgetItem(str(key)))
            self._props.setItem(row, 1, QTableWidgetItem(str(value)))
        self._props.resizeColumnToContents(0)

    # --------------------------------------------------------------- handlers
    def _on_copy_smiles(self) -> None:
        """Put the canonical SMILES on the system clipboard."""
        if self._record is not None:
            QApplication.clipboard().setText(self._record.smiles)
            logger.info("Copied SMILES for %s to clipboard", self._record.name)

    def _on_save_image(self) -> None:
        """Export the current depiction as an SVG or PNG file."""
        if self._record is None:
            return
        safe_name = "".join(c for c in self._record.name if c.isalnum() or c in "-_ ")
        filename, chosen_filter = QFileDialog.getSaveFileName(
            self,
            "Save Structure Image",
            f"{safe_name or 'structure'}.svg",
            "SVG image (*.svg);;PNG image (*.png)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            if path.suffix.lower() == ".png" or "PNG" in chosen_filter:
                self._save_png(path.with_suffix(".png"))
            else:
                path.with_suffix(".svg").write_text(self._svg_text, encoding="utf-8")
        except OSError as exc:
            logger.exception("Failed to save structure image")
            QMessageBox.warning(self, "Save failed", str(exc))
        else:
            logger.info("Saved structure image to %s", path)

    def _save_png(self, path: Path) -> None:
        """Rasterize the SVG at export resolution and write a PNG."""
        renderer = QSvgRenderer(QByteArray(self._svg_text.encode("utf-8")))
        image = QImage(_EXPORT_W, _EXPORT_H, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(path), "PNG"):
            raise OSError(f"Could not write {path}")
