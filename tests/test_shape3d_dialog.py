"""Tests for the 3D shape dialog and its table/panel wiring (offscreen Qt)."""

from __future__ import annotations

import pytest
from rdkit import Chem

from wawekit.gui.dialogs.shape3d_dialog import Shape3DDialog, parse_shells
from wawekit.gui.widgets.molecule_table import MoleculeTableModel
from wawekit.models.conformers import ConformerOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.shape3d import (
    SHAPE3D_SPECS,
    CenterMode,
    ConformerChoice,
    ShellNormalization,
)
from wawekit.services.chemistry.shape3d import compute_shape_descriptors


def _record(smiles: str = "c1ccccc1", name: str = "benzene") -> MoleculeRecord:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return MoleculeRecord(mol=mol, name=name)


def _measured_record() -> MoleculeRecord:
    record = _record()
    compute_shape_descriptors([record], generate_missing=ConformerOptions(n_confs=2, random_seed=1))
    assert record.shape3d is not None
    return record


# --- shell parsing ---------------------------------------------------------


def test_parse_shells_accepts_commas_and_spaces():
    assert parse_shells("3, 6") == (3.0, 6.0)
    assert parse_shells("2 4 6") == (2.0, 4.0, 6.0)
    assert parse_shells(" 3.5 ") == (3.5,)


def test_parse_shells_rejects_junk_and_emptiness():
    with pytest.raises(ValueError):
        parse_shells("")
    with pytest.raises(ValueError):
        parse_shells("   ")
    with pytest.raises(ValueError):
        parse_shells("three, six")


# --- the dialog ------------------------------------------------------------


def test_dialog_defaults_round_trip_to_options(qtbot):
    dialog = Shape3DDialog()
    qtbot.addWidget(dialog)

    options = dialog.options()
    assert options.shells == (3.0, 6.0)
    assert options.center == CenterMode.CENTRE_OF_MASS
    assert options.normalization == ShellNormalization.PER_CARBON
    assert options.conformer == ConformerChoice.LOWEST_ENERGY
    assert options.cumulative is True
    assert options.include_hydrogens is False


def test_dialog_controls_reach_the_options_object(qtbot):
    dialog = Shape3DDialog()
    qtbot.addWidget(dialog)

    dialog._shells.setText("2, 4, 8")
    dialog._center.setCurrentIndex(list(CenterMode).index(CenterMode.CENTROID))
    dialog._normalization.setCurrentIndex(list(ShellNormalization).index(ShellNormalization.COUNT))
    dialog._conformer.setCurrentIndex(list(ConformerChoice).index(ConformerChoice.MEAN))
    dialog._cumulative.setChecked(False)
    dialog._include_h.setChecked(True)

    options = dialog.options()
    assert options.shells == (2.0, 4.0, 8.0)
    assert options.center == CenterMode.CENTROID
    assert options.normalization == ShellNormalization.COUNT
    assert options.conformer == ConformerChoice.MEAN
    assert options.cumulative is False
    assert options.include_hydrogens is True


def test_out_of_order_shells_are_rejected_by_the_options_object(qtbot):
    dialog = Shape3DDialog()
    qtbot.addWidget(dialog)
    dialog._shells.setText("6, 3")
    with pytest.raises(ValueError):
        dialog.options()


def test_conformer_generation_can_be_turned_off(qtbot):
    dialog = Shape3DDialog()
    qtbot.addWidget(dialog)

    assert dialog.conformer_options() is not None  # on by default
    dialog._generate.setChecked(False)
    assert dialog.conformer_options() is None


# --- the table columns -----------------------------------------------------


def test_shape_columns_are_blank_until_measured(qtbot):
    model = MoleculeTableModel()
    model.set_records([_record()])

    for column in _shape_columns(model):
        assert model.data(model.index(0, column)) == ""
        assert model.data(model.index(0, column), role=256) is None  # UserRole sort key


def test_shape_columns_fill_in_after_measurement(qtbot):
    model = MoleculeTableModel()
    model.set_records([_measured_record()])

    values = [model.data(model.index(0, column)) for column in _shape_columns(model)]
    assert all(value != "" for value in values)
    assert values[0] == "disc"  # benzene, the Shape column


def test_shape_headers_carry_their_tooltips(qtbot):
    from PySide6.QtCore import Qt

    model = MoleculeTableModel()
    for offset, column in enumerate(_shape_columns(model)):
        tooltip = model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        assert tooltip == SHAPE3D_SPECS[offset].tooltip


def test_shape_cell_tooltip_carries_radial_values_and_protocol(qtbot):
    from PySide6.QtCore import Qt

    model = MoleculeTableModel()
    model.set_records([_measured_record()])
    first = _shape_columns(model)[0]

    tooltip = model.data(model.index(0, first), role=Qt.ItemDataRole.ToolTipRole)
    # The radial values have no columns of their own; this hover is where they
    # surface, together with the geometry protocol that makes them comparable.
    assert "r3_sp3C_C" in tooltip
    assert "r6_aroC_C" in tooltip
    assert "Geometry:" in tooltip


def test_descriptor_and_shape_panels_do_not_overlap(qtbot):
    model = MoleculeTableModel()
    shape_columns = _shape_columns(model)
    for column in shape_columns:
        assert not MoleculeTableModel._is_descriptor_column(column)
        assert MoleculeTableModel._is_shape3d_column(column)
    # And the panel is exactly as wide as the spec list.
    assert len(shape_columns) == len(SHAPE3D_SPECS)


# --- the 3D viewer shell overlay ------------------------------------------
#
# The WebEngine view cannot be screenshotted under the offscreen platform, so
# these assert on the JavaScript the panel emits instead: that is the actual
# contract between the panel and 3Dmol.js, and it is what would silently break.


def _captured_panel(qtbot, record):
    """Build a ConformerPanel whose viewer records JS instead of running it."""
    from wawekit.gui.widgets.conformer_panel import ConformerPanel

    panel = ConformerPanel()
    qtbot.addWidget(panel)
    scripts: list[str] = []
    panel._view._loaded = True  # pretend the page finished loading
    panel._view._run = scripts.append
    panel.set_record(record)
    return panel, scripts


def test_selecting_a_measured_record_draws_its_shells(qtbot):
    record = _measured_record()
    _panel, scripts = _captured_panel(qtbot, record)

    shells = [s for s in scripts if s.startswith("wawekitShells(")]
    # Populating a record renders the first conformer twice (selectRow fires the
    # row-changed handler, then _populate shows it explicitly) — pre-existing
    # behaviour that wawekitLoad has always had. The overlay inherits it and is
    # idempotent, so assert the payload, not the call count.
    assert shells
    call = shells[-1]
    # Both default radii reach the page, innermost first.
    assert "3.0" in call and "6.0" in call
    # And the centre is the one the descriptors were actually measured from.
    for coordinate in record.shape3d.center:
        assert f"{coordinate}" in call or f"{round(coordinate, 6)}" in call


def test_unmeasured_record_clears_shells_rather_than_drawing_them(qtbot):
    record = _record()
    from wawekit.models.conformers import ConformerOptions as _CO
    from wawekit.services.chemistry.conformers import generate_conformers

    generate_conformers([record], _CO(n_confs=2, random_seed=1))
    assert record.shape3d is None  # geometry but no shape descriptors

    _panel, scripts = _captured_panel(qtbot, record)
    assert any(s.startswith("wawekitClearShells(") for s in scripts)
    assert not any(s.startswith("wawekitShells(") for s in scripts)


def test_shells_are_recentred_for_a_conformer_that_was_not_measured(qtbot):
    """A stored centre belongs to one conformer; others must be recomputed.

    Drawing the stored centre over a different conformer would put the spheres
    somewhere nothing was ever measured — visually plausible and wrong.
    """
    record = _record("OCCCCCCO", "diol")
    compute_shape_descriptors([record], generate_missing=ConformerOptions(n_confs=6, random_seed=1))
    conformers = record.conformers.conformers
    if len(conformers) < 2:
        pytest.skip("embedding produced a single conformer; nothing to switch to")

    panel, scripts = _captured_panel(qtbot, record)
    measured_call = [s for s in scripts if s.startswith("wawekitShells(")][-1]

    other = next(c for c in conformers if c.conf_id != record.shape3d.conf_id)
    scripts.clear()
    panel._show_conformer(other.conf_id)
    other_call = [s for s in scripts if s.startswith("wawekitShells(")][-1]

    assert other_call != measured_call  # a different centre, not the stored one


def _shape_columns(model: MoleculeTableModel) -> list[int]:
    """Locate the 3D shape panel by asking the model, not by hardcoding indices."""
    return [
        column
        for column in range(model.columnCount())
        if MoleculeTableModel._is_shape3d_column(column)
    ]
