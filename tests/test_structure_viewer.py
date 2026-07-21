"""Tests for the structure viewer panel (headless, offscreen Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.gui.widgets.structure_viewer import StructureViewerPanel
from wawekit.models.molecule import MoleculeRecord


def _record(smiles: str, name: str, **props) -> MoleculeRecord:
    return MoleculeRecord(mol=Chem.MolFromSmiles(smiles), name=name, properties=props)


def test_starts_with_placeholder(qtbot):
    panel = StructureViewerPanel()
    qtbot.addWidget(panel)

    assert panel.record is None
    assert panel._depiction_stack.currentWidget() is panel._placeholder
    assert not panel._copy_button.isEnabled()


def test_set_record_shows_structure_and_details(qtbot):
    panel = StructureViewerPanel()
    qtbot.addWidget(panel)

    record = _record("CC(=O)Oc1ccccc1C(=O)O", "aspirin", pIC50="3.5", series="nsaid")
    panel.set_record(record)

    assert panel.record is record
    assert panel._depiction_stack.currentWidget() is panel._svg
    assert panel._name_label.text() == "aspirin"
    assert "C9H8O4" in panel._formula_label.text()
    assert panel._props.rowCount() == 2
    assert panel._copy_button.isEnabled()


def test_set_record_none_returns_to_placeholder(qtbot):
    panel = StructureViewerPanel()
    qtbot.addWidget(panel)

    panel.set_record(_record("CCO", "ethanol"))
    panel.set_record(None)

    assert panel._depiction_stack.currentWidget() is panel._placeholder
    assert panel._name_label.text() == ""
    assert panel._props.rowCount() == 0


def test_copy_smiles_uses_clipboard(qtbot):
    from PySide6.QtWidgets import QApplication

    panel = StructureViewerPanel()
    qtbot.addWidget(panel)
    panel.set_record(_record("CCO", "ethanol"))

    panel._on_copy_smiles()
    assert QApplication.clipboard().text() == "CCO"


def test_theme_switch_rerenders(qtbot):
    panel = StructureViewerPanel(dark=True)
    qtbot.addWidget(panel)
    panel.set_record(_record("c1ccccc1", "benzene"))

    dark_svg = panel._svg_text
    panel.set_dark(False)
    assert panel._svg_text != dark_svg
