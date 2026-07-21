"""Tests for the molecule table model and panel (headless, offscreen Qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from rdkit import Chem

from wawekit.gui.widgets.molecule_table import (
    _FINGERPRINT_COLUMN,
    _FIRST_DESCRIPTOR_COLUMN,
    _SOURCE_COLUMN,
    ALERTS_COLUMN,
    SCAFFOLD_COLUMN,
    SIMILARITY_COLUMN,
    MoleculeTableModel,
    MoleculeTablePanel,
)
from wawekit.gui.widgets.structure_delegate import RECORD_ROLE
from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation
from wawekit.services.chemistry.alerts import compute_alerts_for_records
from wawekit.services.chemistry.descriptors import compute_descriptors
from wawekit.services.chemistry.fingerprints import compute_fingerprints
from wawekit.services.chemistry.scaffolds import compute_scaffolds
from wawekit.services.chemistry.similarity import SimilarityRequest, search_similar

ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
GLUCOSE = "OCC1OC(O)C(O)C(O)C1O"


def _records(*smiles_names: tuple[str, str]) -> list[MoleculeRecord]:
    return [
        MoleculeRecord(mol=Chem.MolFromSmiles(smiles), name=name) for smiles, name in smiles_names
    ]


def test_model_starts_empty(qtbot):
    model = MoleculeTableModel()
    assert model.rowCount() == 0
    # 6 leading (# Structure Name SMILES Formula "Heavy atoms") + descriptor
    # panel + Fingerprint + Similarity + Scaffold + Cluster + Substructure +
    # Alerts + Source.
    assert model.columnCount() == 6 + len(DESCRIPTOR_SPECS) + 7


def test_model_append_and_display(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol"), ("c1ccccc1", "benzene")))

    assert model.rowCount() == 2
    assert model.data(model.index(0, 2)) == "ethanol"
    assert model.data(model.index(1, 4)) == "C6H6"
    assert model.data(model.index(0, 0)) == "1"  # 1-based row number
    assert model.data(model.index(0, 1)) is None  # structure column: delegate paints it
    # UserRole exposes raw values for numeric sorting.
    assert model.data(model.index(1, 5), Qt.ItemDataRole.UserRole) == 6


def test_model_exposes_record_through_custom_role(qtbot):
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)

    assert model.data(model.index(0, 1), RECORD_ROLE) is records[0]


def test_model_clear(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    model.clear()
    assert model.rowCount() == 0


def test_panel_appends_and_counts(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)

    panel.append_records(_records(("CCO", "ethanol"), ("CC(=O)O", "acetic acid")))
    assert panel.row_count == 2
    assert panel.model.record_at(0).name == "ethanol"


def test_panel_emits_selection_changed(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    panel.append_records(_records(("CCO", "ethanol"), ("c1ccccc1", "benzene")))

    # setCurrentIndex is deterministic (selectRow can emit an intermediate
    # current-index change first, which waitSignal would capture instead).
    with qtbot.waitSignal(panel.selection_changed, timeout=1000) as blocker:
        panel._view.setCurrentIndex(panel._proxy.index(1, 0))

    record = blocker.args[0]
    assert isinstance(record, MoleculeRecord)
    assert record.name == "benzene"


# ------------------------------------------------------------- descriptors
def test_descriptor_cells_blank_until_computed(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    # MW is the first descriptor column; empty string before computation.
    assert model.data(model.index(0, _FIRST_DESCRIPTOR_COLUMN)) == ""


def test_descriptor_cells_show_formatted_values_after_compute(qtbot):
    model = MoleculeTableModel()
    records = _records(("CC(=O)Oc1ccccc1C(=O)O", "aspirin"))
    model.append_records(records)
    compute_descriptors(records)
    model.descriptors_updated()
    # MW formatted to two decimals.
    assert model.data(model.index(0, _FIRST_DESCRIPTOR_COLUMN)) == "180.16"


def test_descriptor_header_carries_tooltip(qtbot):
    model = MoleculeTableModel()
    tip = model.headerData(
        _FIRST_DESCRIPTOR_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole
    )
    assert isinstance(tip, str) and "Molecular weight" in tip


# ----------------------------------------------------------- quick-filter
def test_text_filter_hides_non_matching_rows(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    panel.append_records(_records(("CCO", "ethanol"), ("c1ccccc1", "benzene")))

    panel._on_filter_changed("benzene")
    assert panel.visible_row_count == 1
    assert panel.row_count == 2  # data untouched; only visibility changed


def test_numeric_filter_applies_only_after_descriptors(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    records = _records(("CCO", "ethanol"), ("c1ccc2c(c1)ccc1ccccc12", "anthracene"))
    panel.append_records(records)

    panel._on_filter_changed("MW < 100")
    assert panel.visible_row_count == 0  # nothing computed yet → nothing matches

    compute_descriptors(records)
    panel.refresh_descriptors()
    # ethanol (~46) matches, anthracene (~178) does not.
    assert panel.visible_row_count == 1


# ------------------------------------------------------------ fingerprints
def test_fingerprint_cell_blank_until_computed(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    assert model.data(model.index(0, _FINGERPRINT_COLUMN)) == ""


def test_fingerprint_cell_summarises_after_compute(qtbot):
    model = MoleculeTableModel()
    records = _records(("CC(=O)Oc1ccccc1C(=O)O", "aspirin"))
    model.append_records(records)
    compute_fingerprints(records)
    model.fingerprints_updated()

    text = model.data(model.index(0, _FINGERPRINT_COLUMN))
    assert text.startswith("Morgan · ")
    assert text.endswith(" on")


def test_fingerprint_sorts_by_bit_count_not_text(qtbot):
    # "9 on" must sort before "24 on"; string ordering would get that backwards.
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"), ("CC(=O)Oc1ccccc1C(=O)O", "aspirin"))
    model.append_records(records)
    compute_fingerprints(records)

    sort_value = model.data(model.index(0, _FINGERPRINT_COLUMN), Qt.ItemDataRole.UserRole)
    assert sort_value == records[0].fingerprint.n_on_bits
    assert isinstance(sort_value, int)


def test_fingerprint_cell_tooltip_carries_full_parameters(qtbot):
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)
    compute_fingerprints(records)

    tip = model.data(model.index(0, _FINGERPRINT_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert "Morgan r2" in tip and "2048" in tip


def test_alerts_cell_blank_until_computed(qtbot):
    # Regression: this must read as blank, not trigger FilterCatalog compute
    # from a paint — see services/chemistry/alerts.py for the full story.
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)

    assert model.data(model.index(0, ALERTS_COLUMN)) == ""
    assert not records[0].alerts_computed  # reading the cell must not trigger it


def test_alerts_cell_blank_sorts_below_computed_rows(qtbot):
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"), ("O=C1C=CC(=O)C=C1", "quinone"))
    model.append_records(records)
    compute_alerts_for_records([records[1]])  # only the quinone gets checked

    pending = model.data(model.index(0, ALERTS_COLUMN), Qt.ItemDataRole.UserRole)
    checked = model.data(model.index(1, ALERTS_COLUMN), Qt.ItemDataRole.UserRole)
    assert pending is None
    assert checked == len(records[1].alerts)  # a real count, not a guessed one
    assert checked > 0


def test_alerts_cell_shows_warning_badge_after_background_compute(qtbot):
    model = MoleculeTableModel()
    records = _records(("O=C1C=CC(=O)C=C1", "quinone"))
    model.append_records(records)
    compute_alerts_for_records(records)
    model.alerts_updated()

    assert model.data(model.index(0, ALERTS_COLUMN)) == f"⚠️ {len(records[0].alerts)}"


def test_alerts_cell_blank_for_a_clean_molecule_after_compute(qtbot):
    # A checked-and-clean molecule must still read as blank, not "⚠️ 0" —
    # the badge only appears when there is something to warn about.
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)
    compute_alerts_for_records(records)
    model.alerts_updated()

    assert model.data(model.index(0, ALERTS_COLUMN)) == ""
    assert records[0].alerts_computed


def test_alerts_tooltip_distinguishes_pending_from_clean(qtbot):
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)

    pending_tip = model.data(model.index(0, ALERTS_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert "pending" in pending_tip.lower()

    compute_alerts_for_records(records)
    clean_tip = model.data(model.index(0, ALERTS_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert "clean" in clean_tip.lower()


def test_panel_refresh_alerts_repaints_the_column(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    records = _records(("O=C1C=CC(=O)C=C1", "quinone"))
    panel.append_records(records)
    compute_alerts_for_records(records)

    panel.refresh_alerts()

    index = panel.model.index(0, ALERTS_COLUMN)
    assert panel.model.data(index) == f"⚠️ {len(records[0].alerts)}"


def test_source_column_still_last_after_inserting_fingerprint(qtbot):
    # The fingerprint column sits between the descriptors and Source; this pins
    # that the trailing column indices did not drift.
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    assert _SOURCE_COLUMN == model.columnCount() - 1
    assert model.data(model.index(0, _SOURCE_COLUMN)) == ""  # in-memory record


# --------------------------------------------------------------- similarity
def _search(records: list[MoleculeRecord], query_smiles: str = ASPIRIN) -> None:
    """Score ``records`` against a query, as MainWindow's worker would."""
    search_similar(
        records,
        SimilarityRequest(query_mol=Chem.MolFromSmiles(query_smiles), query_name="aspirin"),
    )


def test_similarity_cell_blank_until_a_search_runs(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    # Blank, not "0.000": nobody has compared this molecule to anything.
    assert model.data(model.index(0, SIMILARITY_COLUMN)) == ""


def test_similarity_cell_shows_three_decimals_after_a_search(qtbot):
    model = MoleculeTableModel()
    records = _records((ASPIRIN, "aspirin"))
    model.append_records(records)
    _search(records)
    model.similarity_updated()
    assert model.data(model.index(0, SIMILARITY_COLUMN)) == "1.000"


def test_similarity_sorts_by_the_float_not_the_text(qtbot):
    model = MoleculeTableModel()
    records = _records((ASPIRIN, "aspirin"), (GLUCOSE, "glucose"))
    model.append_records(records)
    _search(records)

    value = model.data(model.index(0, SIMILARITY_COLUMN), Qt.ItemDataRole.UserRole)
    assert isinstance(value, float)
    assert value == 1.0


def test_unscored_row_sorts_as_none(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("CCO", "ethanol")))
    assert model.data(model.index(0, SIMILARITY_COLUMN), Qt.ItemDataRole.UserRole) is None


def test_similarity_tooltip_carries_the_query_it_was_measured_against(qtbot):
    model = MoleculeTableModel()
    records = _records((GLUCOSE, "glucose"))
    model.append_records(records)
    _search(records)

    tip = model.data(model.index(0, SIMILARITY_COLUMN), Qt.ItemDataRole.ToolTipRole)
    assert tip == "Tanimoto vs aspirin · Morgan r2 · 2048b"


def test_query_row_is_bold_and_others_are_not(qtbot):
    model = MoleculeTableModel()
    records = _records((ASPIRIN, "aspirin"), (GLUCOSE, "glucose"))
    model.append_records(records)
    _search(records)

    query_font = model.data(model.index(0, SIMILARITY_COLUMN), Qt.ItemDataRole.FontRole)
    other_font = model.data(model.index(1, SIMILARITY_COLUMN), Qt.ItemDataRole.FontRole)
    assert query_font is not None and query_font.bold()
    assert other_font is None


def test_similarity_header_carries_tooltip(qtbot):
    model = MoleculeTableModel()
    tip = model.headerData(
        SIMILARITY_COLUMN, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole
    )
    assert isinstance(tip, str) and "Sim >= 0.7" in tip


def test_refresh_similarity_ranks_the_table_best_first(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    # Deliberately loaded worst-first, so load order cannot fake the result.
    records = _records((GLUCOSE, "glucose"), (ASPIRIN, "aspirin"))
    panel.append_records(records)

    _search(records)
    panel.refresh_similarity()

    # Row 0 of the *proxy* is what the user sees at the top.
    top = panel._proxy.index(0, SIMILARITY_COLUMN).data(RECORD_ROLE)
    assert top.name == "aspirin"


def test_sim_filter_applies_only_after_a_search(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    records = _records((ASPIRIN, "aspirin"), (GLUCOSE, "glucose"))
    panel.append_records(records)

    panel._on_filter_changed("Sim >= 0.7")
    assert panel.visible_row_count == 0  # nothing scored yet → nothing matches

    _search(records)
    panel.refresh_similarity()
    # Only aspirin (1.000) clears the bar; glucose is nothing like it.
    assert panel.visible_row_count == 1
    assert panel.row_count == 2  # data untouched


def _find_similar_action(panel: MoleculeTablePanel):
    """Return the context menu's 'Find Similar' action, or None if not offered."""
    menu = panel._build_context_menu()
    if menu is None:
        return None
    return next((a for a in menu.actions() if "Similar" in a.text()), None)


def test_context_menu_find_similar_emits_the_selected_record(qtbot):
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    panel.append_records(_records(("CCO", "ethanol"), ("c1ccccc1", "benzene")))
    panel._view.setCurrentIndex(panel._proxy.index(1, 0))

    action = _find_similar_action(panel)
    assert action is not None

    with qtbot.waitSignal(panel.similarity_requested, timeout=1000) as blocker:
        action.trigger()

    assert blocker.args[0].name == "benzene"


def test_context_menu_hides_find_similar_for_a_multi_selection(qtbot):
    # "Similar to these five" is a different question (clustering, Module 11).
    # Silently using the first of five would be a small lie.
    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    panel.append_records(_records(("CCO", "ethanol"), ("c1ccccc1", "benzene")))
    panel._view.selectAll()

    assert len(panel.selected_records()) == 2
    assert _find_similar_action(panel) is None


# ---------------------------------------------------------------- scaffolds
def test_scaffold_cell_blank_until_analysed(qtbot):
    model = MoleculeTableModel()
    model.append_records(_records(("c1ccccc1", "benzene")))
    assert model.data(model.index(0, SCAFFOLD_COLUMN)) == ""


def test_scaffold_cell_shows_core_after_analysis(qtbot):
    model = MoleculeTableModel()
    records = _records(("CC(=O)Nc1ccccc1", "acetanilide"))
    model.append_records(records)
    compute_scaffolds(records)
    model.scaffolds_updated()
    assert model.data(model.index(0, SCAFFOLD_COLUMN)) == "c1ccccc1"


def test_scaffold_cell_marks_acyclic_molecules(qtbot):
    model = MoleculeTableModel()
    records = _records(("CCO", "ethanol"))
    model.append_records(records)
    compute_scaffolds(records)
    model.scaffolds_updated()
    assert model.data(model.index(0, SCAFFOLD_COLUMN)) == "(acyclic)"


def test_scaffold_column_follows_representation(qtbot):
    model = MoleculeTableModel()
    records = _records(("c1ccncc1", "pyridine"))
    model.append_records(records)
    compute_scaffolds(records)
    model.scaffolds_updated()

    # Exact Murcko keeps the nitrogen; the generic framework is all-carbon.
    assert model.data(model.index(0, SCAFFOLD_COLUMN)) == records[0].scaffold.murcko_smiles
    model.set_scaffold_representation(ScaffoldRepresentation.GENERIC)
    assert model.data(model.index(0, SCAFFOLD_COLUMN)) == records[0].scaffold.generic_smiles


def test_scaffold_filter_restricts_to_members(qtbot):
    from wawekit.gui.widgets.molecule_filter import ScaffoldFilter

    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    records = _records(("Nc1ccccc1", "aniline"), ("Oc1ccccc1", "phenol"), ("c1ccncc1", "pyridine"))
    panel.append_records(records)
    compute_scaffolds(records)
    panel.refresh_scaffolds()

    panel.apply_scaffold_filter(ScaffoldFilter("c1ccccc1", ScaffoldRepresentation.MURCKO))
    assert panel.visible_row_count == 2  # aniline + phenol share benzene
    assert panel.row_count == 3  # data untouched

    panel.apply_scaffold_filter(None)
    assert panel.visible_row_count == 3


def test_scaffold_filter_ands_with_text_filter(qtbot):
    from wawekit.gui.widgets.molecule_filter import ScaffoldFilter

    panel = MoleculeTablePanel()
    qtbot.addWidget(panel)
    records = _records(("Nc1ccccc1", "aniline"), ("Oc1ccccc1", "phenol"))
    panel.append_records(records)
    compute_scaffolds(records)
    panel.refresh_scaffolds()

    # Both share benzene, but the text filter narrows to one.
    panel.apply_scaffold_filter(ScaffoldFilter("c1ccccc1", ScaffoldRepresentation.MURCKO))
    panel._on_filter_changed("phenol")
    assert panel.visible_row_count == 1
