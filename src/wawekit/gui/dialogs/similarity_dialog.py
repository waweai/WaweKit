"""Dialog for configuring a similarity search.

Two questions, answered in the order a chemist thinks of them:

1. **Similar to what?** Either the row currently selected in the table, or a
   SMILES pasted in. Both are standard practice — you search for more compounds
   like your hit (selection), or you search a library for something you saw in
   a paper and never loaded (paste).
2. **Similar by what measure?** The metric, and the encoding both sides use.

Live validation, not a wall
---------------------------
The pasted-SMILES box validates as you type and OK stays disabled until the
query actually parses. The alternative — accept anything, fail after the dialog
closes — makes the user re-open the dialog and re-type to find out what was
wrong. Validating in place puts the error next to the thing that caused it.

The dialog never imports RDKit: parsing goes through
:func:`~wawekit.services.io.molecule_loader.parse_smiles`, keeping the layering
rule ``gui -> services -> models -> core`` intact. A GUI that knows chemistry is
a GUI you cannot test headlessly or reuse from a script.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.similarity import SimilarityMetric
from wawekit.services.chemistry.similarity import SimilarityRequest
from wawekit.services.io.molecule_loader import parse_smiles

#: What each metric is for, in one line, shown under the selector.
_METRIC_HELP = {
    SimilarityMetric.TANIMOTO: (
        "Shared bits ÷ union. The field default — published thresholds "
        "(e.g. “similar” ≥ 0.85) assume it."
    ),
    SimilarityMetric.DICE: (
        "Counts shared bits twice, so scores run higher. Fairer when the two "
        "molecules differ a lot in size."
    ),
    SimilarityMetric.COSINE: (
        "The angle between the two bit vectors. Common in chemical-space work."
    ),
}


class SimilarityDialog(QDialog):
    """Choose a query molecule, a metric and an encoding for a similarity search.

    Parameters
    ----------
    selected:
        The record currently selected in the table, or ``None``. Decides whether
        the "use selection" option is offered at all.
    fingerprint:
        Encoding to pre-select — pass the dataset's current fingerprint options
        so a second search doesn't silently re-encode everything a new way.

    """

    def __init__(
        self,
        selected: MoleculeRecord | None = None,
        fingerprint: FingerprintOptions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Similarity Search")
        self.setModal(True)
        self._selected = selected

        intro = QLabel(
            "Rank every molecule in the dataset by how similar it is to one query.",
            self,
        )

        # ---- 1. the query ------------------------------------------------
        query_box = QGroupBox("Query molecule", self)

        self._use_selection = QRadioButton(self)
        self._use_paste = QRadioButton("Paste SMILES:", self)

        if selected is not None:
            self._use_selection.setText(f"Selected molecule:  {selected.name}")
            self._use_selection.setChecked(True)
        else:
            self._use_selection.setText("Selected molecule:  (none selected)")
            self._use_selection.setEnabled(False)
            self._use_paste.setChecked(True)
        self._use_selection.toggled.connect(self._sync_query_state)

        self._selected_smiles = QLabel(self)
        self._selected_smiles.setObjectName("queryStructure")
        self._selected_smiles.setWordWrap(True)
        if selected is not None:
            self._selected_smiles.setText(selected.smiles)

        self._smiles_edit = QLineEdit(self)
        self._smiles_edit.setClearButtonEnabled(True)
        self._smiles_edit.setPlaceholderText("e.g. CC(=O)Oc1ccccc1C(=O)O")
        self._smiles_edit.textChanged.connect(self._sync_query_state)

        self._query_status = QLabel(self)
        self._query_status.setObjectName("queryStatus")
        self._query_status.setWordWrap(True)

        query_layout = QVBoxLayout(query_box)
        query_layout.addWidget(self._use_selection)
        query_layout.addWidget(self._selected_smiles)
        query_layout.addWidget(self._use_paste)
        query_layout.addWidget(self._smiles_edit)
        query_layout.addWidget(self._query_status)

        # ---- 2. the measure ----------------------------------------------
        metric_box = QGroupBox("Measure", self)

        self._metric = QComboBox(self)
        for metric in SimilarityMetric:
            # Enum as item data — coerced back in _selected_metric (see there).
            self._metric.addItem(str(metric), metric)
        self._metric.setCurrentIndex(self._metric.findData(SimilarityMetric.TANIMOTO))
        self._metric.currentIndexChanged.connect(self._sync_metric_help)

        self._metric_help = QLabel(self)
        self._metric_help.setWordWrap(True)
        self._metric_help.setObjectName("metricHelp")

        metric_layout = QVBoxLayout(metric_box)
        metric_layout.addWidget(self._metric)
        metric_layout.addWidget(self._metric_help)

        # ---- 3. the encoding ---------------------------------------------
        encoding_box = QGroupBox("Encoding (applied to the query and the dataset)", self)
        self._fingerprint = FingerprintOptionsWidget(encoding_box)
        if fingerprint is not None:
            self._fingerprint.set_options(fingerprint)
        encoding_layout = QVBoxLayout(encoding_box)
        encoding_layout.addWidget(self._fingerprint)

        hint = QLabel(
            "Results appear in the Similarity column, sorted best first.\n"
            "Filter them with a query like “Sim >= 0.7”.",
            self,
        )
        hint.setObjectName("similarityHint")

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Search")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(4)
        layout.addWidget(query_box)
        layout.addWidget(metric_box)
        layout.addWidget(encoding_box)
        layout.addWidget(hint)
        layout.addSpacing(4)
        layout.addWidget(self._buttons)

        self._sync_metric_help()
        self._sync_query_state()

    # ---------------------------------------------------------------- helpers
    def _selected_metric(self) -> SimilarityMetric:
        """Return the metric chosen, as a real enum member.

        Same ``QVariant`` trap as the fingerprint kind (Module 6): a
        :class:`~enum.StrEnum` handed to ``addItem`` comes back out of
        ``currentData()`` as a plain ``str``, and every ``is`` check against it
        then quietly fails. Coerce at the Qt boundary, once.
        """
        return SimilarityMetric(self._metric.currentData())

    def _sync_metric_help(self) -> None:
        """Explain the metric currently selected."""
        self._metric_help.setText(_METRIC_HELP[self._selected_metric()])

    def _query_record(self) -> MoleculeRecord | None:
        """Resolve the current query choice to a record, or ``None`` if unusable."""
        if self._use_selection.isChecked():
            return self._selected
        return parse_smiles(self._smiles_edit.text(), name="Pasted query")

    def _sync_query_state(self) -> None:
        """Enable the right controls, validate the paste, and gate the OK button.

        Runs on every keystroke, which is what makes the feedback live. It is
        cheap: parsing one SMILES is microseconds, far below the threshold where
        a user would notice.
        """
        pasting = self._use_paste.isChecked()
        self._smiles_edit.setEnabled(pasting)
        self._selected_smiles.setEnabled(not pasting)

        record = self._query_record()
        if pasting:
            typed = self._smiles_edit.text().strip()
            if not typed:
                self._query_status.setText("Enter a SMILES string to search for.")
            elif record is None:
                self._query_status.setText("⚠ Not a valid SMILES string.")
            else:
                self._query_status.setText(f"✓ {record.formula} · {record.num_heavy_atoms} atoms")
        else:
            self._query_status.setText("")

        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(record is not None)

    # ------------------------------------------------------------- public API
    def request(self) -> SimilarityRequest | None:
        """Build the search request from the current widget states.

        ``None`` if no usable query is selected — which the OK button already
        prevents, but a caller should not have to know that to be safe.
        """
        record = self._query_record()
        if record is None:
            return None
        return SimilarityRequest(
            query_mol=record.mol,
            query_name=record.name,
            metric=self._selected_metric(),
            fingerprint=self._fingerprint.options(),
        )

    @staticmethod
    def get_request(
        selected: MoleculeRecord | None = None,
        fingerprint: FingerprintOptions | None = None,
        parent: QWidget | None = None,
    ) -> SimilarityRequest | None:
        """Show the dialog modally; return a request, or ``None`` if cancelled."""
        dialog = SimilarityDialog(selected, fingerprint, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.request()
        return None
