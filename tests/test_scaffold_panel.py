"""Tests for the Scaffolds panel (headless, offscreen Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.gui.widgets.scaffold_panel import ScaffoldPanel
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation
from wawekit.services.chemistry.scaffolds import compute_scaffolds, group_scaffolds


def _records(*smiles_names: tuple[str, str]) -> list[MoleculeRecord]:
    recs = [
        MoleculeRecord(mol=Chem.MolFromSmiles(smiles), name=name) for smiles, name in smiles_names
    ]
    compute_scaffolds(recs)
    return recs


def test_starts_with_placeholder(qtbot):
    panel = ScaffoldPanel()
    qtbot.addWidget(panel)
    assert panel._stack.currentWidget() is panel._placeholder


def test_set_groups_populates_list_and_headline(qtbot):
    panel = ScaffoldPanel()
    qtbot.addWidget(panel)
    records = _records(("Nc1ccccc1", "aniline"), ("Oc1ccccc1", "phenol"), ("CCO", "ethanol"))
    groups = group_scaffolds(records, ScaffoldRepresentation.MURCKO)

    panel.set_groups(groups, ScaffoldRepresentation.MURCKO, len(records))

    assert panel._stack.currentWidget() is panel._list
    # benzene group (2) + acyclic group (1) = 2 rows
    assert panel._list.count() == 2
    assert "distinct scaffold" in panel._headline.text()


def test_selecting_a_scaffold_emits_group(qtbot):
    panel = ScaffoldPanel()
    qtbot.addWidget(panel)
    records = _records(("Nc1ccccc1", "aniline"), ("Oc1ccccc1", "phenol"))
    groups = group_scaffolds(records, ScaffoldRepresentation.MURCKO)
    panel.set_groups(groups, ScaffoldRepresentation.MURCKO, len(records))

    with qtbot.waitSignal(panel.scaffold_selected, timeout=1000) as blocker:
        panel._list.setCurrentRow(0)

    emitted = blocker.args[0]
    assert emitted.key == "c1ccccc1"
    assert emitted.size == 2


def test_show_all_emits_none(qtbot):
    panel = ScaffoldPanel()
    qtbot.addWidget(panel)
    records = _records(("Nc1ccccc1", "aniline"))
    panel.set_groups(
        group_scaffolds(records, ScaffoldRepresentation.MURCKO),
        ScaffoldRepresentation.MURCKO,
        len(records),
    )
    panel._list.setCurrentRow(0)

    with qtbot.waitSignal(panel.scaffold_selected, timeout=1000) as blocker:
        panel._on_show_all()
    assert blocker.args[0] is None


def test_representation_toggle_emits(qtbot):
    panel = ScaffoldPanel()
    qtbot.addWidget(panel)

    with qtbot.waitSignal(panel.representation_changed, timeout=1000) as blocker:
        panel._generic_radio.setChecked(True)
    assert blocker.args[0] == ScaffoldRepresentation.GENERIC
