"""Dialog to configure a standardization-reproducibility audit.

Two kinds of standardizer can be compared, and the dialog keeps them visually
separate because they answer different questions and carry different
capabilities:

* **Composed protocols** — subsets of RDKit operations. Because their steps are
  individually addressable, these are the only ones that support ablation-based
  cause attribution.
* **Production pipelines** — ChEMBL's own curation code and MolVS, invoked as
  black boxes. These answer "does my pipeline agree with the one this database
  runs?", which is the question that arises when merging data across sources,
  but they cannot be ablated.

External pipelines are optional dependencies, so their checkboxes appear only
when the corresponding package is installed; a missing package disables the row
with an explanation rather than hiding the capability silently.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from wawekit.services.reproducibility import (
    PRESET_AGGRESSIVE,
    PRESET_CHEMBL_LIKE,
    PRESET_MINIMAL,
)
from wawekit.services.reproducibility.standardizers import (
    ChEMBLPipelineStandardizer,
    MolVSStandardizer,
    ProtocolStandardizer,
    Standardizer,
    available_standardizers,
)


class ReproducibilityDialog(QDialog):
    """Choose standardizers to compare and whether to attribute causes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Standardization Reproducibility Audit")
        self.setModal(True)

        intro = QLabel(
            "Compare standardizers across the dataset: do they agree on each\n"
            "molecule's standard structure, and — where the standardizer allows\n"
            "it — which operation is responsible when they do not?",
            self,
        )

        # --- composed protocols (ablatable) --------------------------------
        self._protocol_boxes: list[tuple[QCheckBox, object]] = []
        for preset in (PRESET_MINIMAL, PRESET_CHEMBL_LIKE, PRESET_AGGRESSIVE):
            box = QCheckBox(preset.label, self)
            box.setChecked(True)
            box.setToolTip("Composed from RDKit operations — supports cause attribution.")
            self._protocol_boxes.append((box, ProtocolStandardizer(preset)))

        # --- production pipelines (opaque) ---------------------------------
        availability = available_standardizers()
        self._external_boxes: list[tuple[QCheckBox, object]] = []

        chembl_box = QCheckBox("ChEMBL pipeline (as the database runs it)", self)
        if availability["ChEMBL pipeline"]:
            chembl_box.setToolTip("Opaque pipeline — compared, but not ablatable.")
            self._external_boxes.append((chembl_box, ChEMBLPipelineStandardizer()))
        else:
            chembl_box.setEnabled(False)
            chembl_box.setText(chembl_box.text() + "  — install chembl_structure_pipeline")

        molvs_default = QCheckBox("MolVS (default configuration)", self)
        molvs_parent = QCheckBox("MolVS (super-parent configuration)", self)
        if availability["MolVS"]:
            for box, super_parent in ((molvs_default, False), (molvs_parent, True)):
                box.setToolTip("Opaque pipeline — compared, but not ablatable.")
                self._external_boxes.append((box, MolVSStandardizer(super_parent=super_parent)))
        else:
            for box in (molvs_default, molvs_parent):
                box.setEnabled(False)
                box.setText(box.text() + "  — install molvs")

        self._causes = QCheckBox("Attribute divergence causes (ablation — slower)", self)
        self._causes.setChecked(True)
        self._causes.setToolTip(
            "Requires at least one composed protocol; production pipelines cannot be ablated."
        )

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run Audit")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._buttons = buttons

        self._hint = QLabel("", self)
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet("color: #b06000;")
        for box, _ in (*self._protocol_boxes, *self._external_boxes):
            box.toggled.connect(self._update_hint)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(QLabel("<b>Composed protocols</b> (support cause attribution):", self))
        for box, _ in self._protocol_boxes:
            layout.addWidget(box)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)

        layout.addWidget(QLabel("<b>Production pipelines</b> (compared, not ablatable):", self))
        layout.addWidget(chembl_box)
        layout.addWidget(molvs_default)
        layout.addWidget(molvs_parent)
        layout.addWidget(self._causes)
        layout.addWidget(self._hint)
        layout.addWidget(buttons)
        self._update_hint()

    # ------------------------------------------------------------- helpers
    def _selected(self) -> tuple[Standardizer, ...]:
        """Return every checked standardizer, protocols first."""
        chosen = [std for box, std in self._protocol_boxes if box.isChecked()]
        chosen.extend(std for box, std in self._external_boxes if box.isChecked())
        return tuple(chosen)

    def _update_hint(self) -> None:
        """Warn when the chosen set cannot support what the user asked for."""
        chosen = self._selected()
        if len(chosen) < 2:
            self._hint.setText(
                "Select at least two standardizers — one cannot diverge from itself."
            )
        elif self._causes.isChecked() and not any(s.is_ablatable for s in chosen):
            self._hint.setText(
                "No composed protocol selected: divergence will be reported, but its "
                "cause cannot be attributed. Add a composed protocol to enable attribution."
            )
        else:
            self._hint.setText("")

    def _on_accept(self) -> None:
        """Require at least two standardizers — one cannot diverge from itself."""
        if len(self._selected()) >= 2:
            self.accept()

    def result_options(self) -> tuple[tuple[Standardizer, ...], bool]:
        """Return ``(standardizers, attribute_causes)`` from the current controls."""
        return self._selected(), self._causes.isChecked()

    @staticmethod
    def get_options(
        parent: QWidget | None = None,
    ) -> tuple[tuple[Standardizer, ...], bool] | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = ReproducibilityDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.result_options()
        return None
