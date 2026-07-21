"""Options dialog for 3D conformer generation.

A focused :class:`~PySide6.QtWidgets.QDialog` exposing the four parameters that
matter: how many conformers, which force field, the pruning RMSD, and the seed.
Uses the same static-factory idiom as the other option dialogs
(:meth:`ConformerDialog.get_options` returns options or ``None`` on cancel).
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.conformers import ConformerOptions, ForceField


class ConformerDialog(QDialog):
    """Lets the user configure conformer generation before it runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate 3D Conformers")
        self.setModal(True)

        defaults = ConformerOptions()

        intro = QLabel(
            "Embed 3D conformers (ETKDG), optimise with a force field, and rank\n"
            "them by energy. Generation runs on your selection, or the whole\n"
            "dataset if nothing is selected.",
            self,
        )

        self._n_confs = QSpinBox(self)
        self._n_confs.setRange(1, 500)
        self._n_confs.setValue(defaults.n_confs)

        # Force-field radios (a StrEnum flows straight to the options object).
        self._ff_group = QButtonGroup(self)
        self._ff_radios: dict[ForceField, QRadioButton] = {}
        ff_box = QVBoxLayout()
        for field in (ForceField.MMFF94, ForceField.UFF, ForceField.NONE):
            radio = QRadioButton(field.label, self)
            radio.setChecked(field == defaults.force_field)
            self._ff_group.addButton(radio)
            self._ff_radios[field] = radio
            ff_box.addWidget(radio)

        self._prune = QDoubleSpinBox(self)
        self._prune.setRange(0.0, 5.0)
        self._prune.setSingleStep(0.1)
        self._prune.setDecimals(2)
        self._prune.setValue(defaults.prune_rms_threshold)
        self._prune.setSuffix(" Å")

        self._seed = QSpinBox(self)
        self._seed.setRange(0, 2_000_000_000)
        self._seed.setValue(defaults.random_seed)

        form = QFormLayout()
        form.addRow("Number of conformers:", self._n_confs)
        form.addRow("Force field:", ff_box)
        form.addRow("Prune RMSD:", self._prune)
        form.addRow("Random seed:", self._seed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _selected_force_field(self) -> ForceField:
        """Return the force field whose radio is checked."""
        for field, radio in self._ff_radios.items():
            if radio.isChecked():
                return field
        return ForceField.MMFF94

    def options(self) -> ConformerOptions:
        """Build an options object from the current control values."""
        return ConformerOptions(
            n_confs=self._n_confs.value(),
            force_field=self._selected_force_field(),
            prune_rms_threshold=self._prune.value(),
            random_seed=self._seed.value(),
        )

    @staticmethod
    def get_options(parent: QWidget | None = None) -> ConformerOptions | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = ConformerDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options()
        return None
