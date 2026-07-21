"""Options dialog for chemical-space projection.

Reuses :class:`~wawekit.gui.widgets.fingerprint_options.FingerprintOptionsWidget`
(now on its third consumer, after the fingerprint and similarity dialogs) so the
encoding choices — and their inter-dependencies — are defined once. The method
radios drive whether the t-SNE perplexity control is enabled, in the same
"only expose parameters that mean something" spirit as that widget.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.services.chemistry.chemical_space import ProjectionMethod, SpaceOptions


class ChemicalSpaceDialog(QDialog):
    """Lets the user pick the projection method and encoding before it runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chemical Space")
        self.setModal(True)

        defaults = SpaceOptions()

        intro = QLabel(
            "Project the dataset into 2D from molecular fingerprints.\n"
            "Each point is a molecule; nearby points are structurally similar.",
            self,
        )

        # --- method radios
        self._method_radios: dict[ProjectionMethod, QRadioButton] = {}
        self._method_group = QButtonGroup(self)
        method_box = QVBoxLayout()
        for method in (ProjectionMethod.PCA, ProjectionMethod.TSNE):
            radio = QRadioButton(method.label, self)
            radio.setChecked(method == defaults.method)
            radio.toggled.connect(self._sync_enabled_state)
            self._method_group.addButton(radio)
            self._method_radios[method] = radio
            method_box.addWidget(radio)
        method_group = QGroupBox("Method", self)
        method_group.setLayout(method_box)

        # --- t-SNE perplexity
        self._perplexity = QDoubleSpinBox(self)
        self._perplexity.setRange(1.0, 100.0)
        self._perplexity.setValue(defaults.perplexity)
        self._perplexity.setToolTip(
            "t-SNE only. Roughly how many neighbours each point balances against; "
            "clamped to the dataset size when small."
        )
        perplexity_form = QFormLayout()
        perplexity_form.addRow("Perplexity (t-SNE):", self._perplexity)

        # --- fingerprint encoding (reused widget)
        self._fingerprint = FingerprintOptionsWidget(self)
        self._fingerprint.set_options(defaults.fingerprint)
        fp_group = QGroupBox("Fingerprint encoding", self)
        fp_layout = QVBoxLayout(fp_group)
        fp_layout.addWidget(self._fingerprint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(method_group)
        layout.addLayout(perplexity_form)
        layout.addWidget(fp_group)
        layout.addWidget(buttons)

        self._sync_enabled_state()

    def _selected_method(self) -> ProjectionMethod:
        """Return the projection method whose radio is checked."""
        for method, radio in self._method_radios.items():
            if radio.isChecked():
                return method
        return ProjectionMethod.PCA

    def _sync_enabled_state(self) -> None:
        """Enable perplexity only for t-SNE (PCA ignores it)."""
        self._perplexity.setEnabled(self._selected_method() == ProjectionMethod.TSNE)

    def options(self) -> SpaceOptions:
        """Build a :class:`SpaceOptions` from the current controls."""
        return SpaceOptions(
            method=self._selected_method(),
            fingerprint=self._fingerprint.options(),
            perplexity=self._perplexity.value(),
        )

    @staticmethod
    def get_options(parent: QWidget | None = None) -> SpaceOptions | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = ChemicalSpaceDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options()
        return None
