"""Options dialog for molecular clustering.

Reuses :class:`~wawekit.gui.widgets.fingerprint_options.FingerprintOptionsWidget`
(now on its fourth consumer) and follows the same "only expose parameters that
mean something" rule: the method radios drive which of the Butina cutoff and the
K-Means cluster count is enabled.
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.models.clustering import ClusterMethod
from wawekit.services.chemistry.clustering import ClusterOptions


class ClusteringDialog(QDialog):
    """Lets the user pick the clustering method and encoding before it runs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cluster Molecules")
        self.setModal(True)

        defaults = ClusterOptions()

        intro = QLabel(
            "Group structurally similar molecules. Butina needs no cluster count "
            "(it\nfollows from the cutoff); K-Means partitions into a fixed K.",
            self,
        )

        # --- method radios
        self._method_radios: dict[ClusterMethod, QRadioButton] = {}
        self._method_group = QButtonGroup(self)
        method_box = QVBoxLayout()
        for method in (ClusterMethod.BUTINA, ClusterMethod.KMEANS):
            radio = QRadioButton(method.label, self)
            radio.setChecked(method == defaults.method)
            radio.toggled.connect(self._sync_enabled_state)
            self._method_group.addButton(radio)
            self._method_radios[method] = radio
            method_box.addWidget(radio)
        method_group = QGroupBox("Method", self)
        method_group.setLayout(method_box)

        # --- parameters
        self._cutoff = QDoubleSpinBox(self)
        self._cutoff.setRange(0.05, 0.95)
        self._cutoff.setSingleStep(0.05)
        self._cutoff.setDecimals(2)
        self._cutoff.setValue(defaults.cutoff)
        self._cutoff.setToolTip(
            "Butina: Tanimoto distance threshold. Lower is stricter — tighter, "
            "more numerous clusters."
        )

        self._n_clusters = QSpinBox(self)
        self._n_clusters.setRange(2, 100)
        self._n_clusters.setValue(defaults.n_clusters)
        self._n_clusters.setToolTip("K-Means: number of clusters to form.")

        params = QFormLayout()
        params.addRow("Butina cutoff:", self._cutoff)
        params.addRow("K-Means clusters:", self._n_clusters)

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
        layout.addLayout(params)
        layout.addWidget(fp_group)
        layout.addWidget(buttons)

        self._sync_enabled_state()

    def _selected_method(self) -> ClusterMethod:
        """Return the clustering method whose radio is checked."""
        for method, radio in self._method_radios.items():
            if radio.isChecked():
                return method
        return ClusterMethod.BUTINA

    def _sync_enabled_state(self) -> None:
        """Enable only the parameter the selected method actually uses."""
        is_butina = self._selected_method() == ClusterMethod.BUTINA
        self._cutoff.setEnabled(is_butina)
        self._n_clusters.setEnabled(not is_butina)

    def options(self) -> ClusterOptions:
        """Build a :class:`ClusterOptions` from the current controls."""
        return ClusterOptions(
            method=self._selected_method(),
            fingerprint=self._fingerprint.options(),
            cutoff=self._cutoff.value(),
            n_clusters=self._n_clusters.value(),
        )

    @staticmethod
    def get_options(parent: QWidget | None = None) -> ClusterOptions | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = ClusteringDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options()
        return None
