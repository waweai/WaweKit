"""Tests for the conformer options dialog (offscreen Qt; no web view)."""

from __future__ import annotations

from wawekit.gui.dialogs.conformer_dialog import ConformerDialog
from wawekit.models.conformers import ConformerOptions, ForceField


def test_defaults_match_the_options_dataclass(qtbot):
    dialog = ConformerDialog()
    qtbot.addWidget(dialog)
    opts = dialog.options()
    defaults = ConformerOptions()

    assert opts.n_confs == defaults.n_confs
    assert opts.force_field == defaults.force_field
    assert opts.prune_rms_threshold == defaults.prune_rms_threshold


def test_edited_values_flow_into_options(qtbot):
    dialog = ConformerDialog()
    qtbot.addWidget(dialog)

    dialog._n_confs.setValue(25)
    dialog._ff_radios[ForceField.UFF].setChecked(True)
    dialog._prune.setValue(1.0)

    opts = dialog.options()
    assert opts.n_confs == 25
    assert opts.force_field == ForceField.UFF
    assert opts.prune_rms_threshold == 1.0


def test_force_field_none_is_selectable(qtbot):
    dialog = ConformerDialog()
    qtbot.addWidget(dialog)
    dialog._ff_radios[ForceField.NONE].setChecked(True)
    assert dialog.options().force_field == ForceField.NONE
