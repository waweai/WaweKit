"""Standalone 3D molecule viewer dock panel.

Renders any selected molecule in interactive 3D using the same vendored
3Dmol.js as the Conformers panel. Unlike that panel, this one does **not**
require prior conformer generation: it creates a quick 3D embedding on the
fly using ``AllChem.EmbedMolecule`` + MMFF optimization, giving an instant
interactive 3D view of whatever is selected in the table.

The panel follows the molecule-table selection signal — same pattern as
:class:`~wawekit.gui.widgets.structure_viewer.StructureViewerPanel`.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.conformer_view import ConformerView
from wawekit.models.molecule import MoleculeRecord

logger = logging.getLogger(__name__)

#: Rendering style presets understood by 3Dmol.js.
_STYLES = {
    "Ball & Stick": "{{ stick: {{ radius: 0.13 }}, sphere: {{ scale: 0.22 }} }}",
    "Stick": "{{ stick: {{ radius: 0.15 }} }}",
    "Space-fill": "{{ sphere: {{}} }}",
    "Wireframe": "{{ line: {{}} }}",
}


def _embed_molecule(mol):
    """Return an MDL mol block with 3D coordinates, or ``None`` on failure.

    Uses RDKit's ETKDGv3 + MMFF for a single fast embedding. This is *not*
    a multi-conformer search — it generates exactly one geometry quickly so the
    viewer has something to show immediately.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol_3d = Chem.RWMol(Chem.AddHs(mol))
    params = AllChem.ETKDGv3()
    params.randomSeed = 42
    result = AllChem.EmbedMolecule(mol_3d, params)
    if result < 0:
        # Fallback: try without the distance-geometry constraints.
        result = AllChem.EmbedMolecule(mol_3d, randomSeed=42)
    if result < 0:
        return None
    try:
        AllChem.MMFFOptimizeMolecule(mol_3d, maxIters=200)
    except Exception:  # noqa: BLE001 — MMFF failure is non-fatal
        pass
    return Chem.MolToMolBlock(mol_3d)


class Viewer3DPanel(QWidget):
    """Interactive 3D view for the currently selected molecule.

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
        self._current_style = "Ball & Stick"

        self._header = QLabel("", self)
        self._header.setWordWrap(True)

        self._view = ConformerView(dark=dark, parent=self)

        self._style_combo = QComboBox(self)
        self._style_combo.addItems(list(_STYLES.keys()))
        self._style_combo.setCurrentText(self._current_style)
        self._style_combo.currentTextChanged.connect(self._on_style_changed)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:", self))
        style_row.addWidget(self._style_combo)
        style_row.addStretch(1)

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(self._header)
        content_layout.addLayout(style_row)
        content_layout.addWidget(self._view, stretch=1)

        self._placeholder = QLabel(
            "Select a molecule in the table\nto see it in 3D.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(content)

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

    # ------------------------------------------------------------- public API
    def set_record(self, record: MoleculeRecord | None) -> None:
        """Generate a 3D embedding of ``record`` and display it, or show placeholder."""
        self._record = record
        if record is None:
            self._stack.setCurrentWidget(self._placeholder)
            self._view.clear()
            return

        molblock = _embed_molecule(record.mol)
        if molblock is None:
            self._header.setText(f"<b>{record.name}</b> — could not generate 3D coordinates")
            self._stack.setCurrentWidget(self._stack.widget(1))
            self._view.clear()
            return

        self._header.setText(
            f"<b>{record.name}</b> — {record.formula} · {record.num_heavy_atoms} heavy atoms"
        )
        self._view.show_molblock(molblock)
        self._apply_style()
        self._stack.setCurrentWidget(self._stack.widget(1))

    def set_dark(self, dark: bool) -> None:
        """Match the 3D viewer background to the application theme."""
        self._view.set_dark(dark)

    # ---------------------------------------------------------------- helpers
    def _apply_style(self) -> None:
        """Apply the current rendering style to the viewer via JavaScript."""
        style_js = _STYLES.get(self._current_style, _STYLES["Ball & Stick"])
        # The style_js template uses {{ }} for literal JS braces in the f-string,
        # so we evaluate it here to get the actual JS object literal.
        js = style_js.format()
        script = f"viewer.setStyle({{}}, {js}); viewer.render();"
        if self._view._loaded:  # noqa: SLF001 — internal, but necessary
            self._view._run(script)  # noqa: SLF001

    # --------------------------------------------------------------- handlers
    def _on_style_changed(self, style_name: str) -> None:
        """Change the rendering style in the 3D viewer."""
        self._current_style = style_name
        if self._record is not None:
            self._apply_style()
