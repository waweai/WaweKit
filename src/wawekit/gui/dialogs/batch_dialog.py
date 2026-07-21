"""Dialog to assemble a batch pipeline.

A pipeline is a checklist of steps, run in fixed chemical order, optionally
followed by an export. The steps that need parameters share one control group:
fingerprints and clustering both use the single
:class:`~wawekit.gui.widgets.fingerprint_options.FingerprintOptionsWidget` (so a
batch cannot encode the two inconsistently), and standardization uses its default
pipeline. Deeper per-step configuration is deliberately left out — a batch is for
running the common recipe over a set, not for fiddling every knob.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.models.clustering import ClusterMethod
from wawekit.services.batch import BatchConfig, ExportFormat
from wawekit.services.chemistry.clustering import ClusterOptions
from wawekit.services.chemistry.standardizer import StandardizationOptions


class BatchDialog(QDialog):
    """Build a :class:`~wawekit.services.batch.BatchConfig` from checkboxes."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch Processing")
        self.setModal(True)

        intro = QLabel(
            "Run a pipeline over the whole dataset, unattended. Steps run in the\n"
            "order shown; the run can be cancelled while it works.",
            self,
        )

        # --- steps
        self._standardize = QCheckBox("Standardize (salts, charges, duplicates)", self)
        self._descriptors = QCheckBox("Compute descriptors", self)
        self._descriptors.setChecked(True)
        self._fingerprints = QCheckBox("Compute fingerprints", self)
        self._scaffolds = QCheckBox("Analyze scaffolds", self)
        self._cluster = QCheckBox("Cluster (Butina)", self)
        steps_box = QVBoxLayout()
        for box in (
            self._standardize,
            self._descriptors,
            self._fingerprints,
            self._scaffolds,
            self._cluster,
        ):
            steps_box.addWidget(box)
        steps_group = QGroupBox("Pipeline steps", self)
        steps_group.setLayout(steps_box)

        # --- cluster cutoff + shared fingerprint encoding
        self._cutoff = QDoubleSpinBox(self)
        self._cutoff.setRange(0.05, 0.95)
        self._cutoff.setSingleStep(0.05)
        self._cutoff.setValue(ClusterOptions().cutoff)
        cutoff_form = QFormLayout()
        cutoff_form.addRow("Butina cutoff:", self._cutoff)

        self._fingerprint_options = FingerprintOptionsWidget(self)
        encoding_group = QGroupBox("Fingerprint encoding (fingerprints + clustering)", self)
        encoding_layout = QVBoxLayout(encoding_group)
        encoding_layout.addWidget(self._fingerprint_options)

        # --- export
        self._export = QCheckBox("Export results", self)
        self._export.setChecked(True)
        self._export.toggled.connect(self._sync_enabled_state)
        self._format = QComboBox(self)
        for fmt in ExportFormat:
            self._format.addItem(str(fmt), fmt)
        self._path = QLineEdit(self)
        self._path.setPlaceholderText("choose an output file…")
        self._browse = QPushButton("Browse…", self)
        self._browse.clicked.connect(self._on_browse)
        self._format.currentIndexChanged.connect(self._on_format_changed)

        path_row = QHBoxLayout()
        path_row.addWidget(self._path, stretch=1)
        path_row.addWidget(self._browse)
        export_form = QFormLayout()
        export_form.addRow(self._export)
        export_form.addRow("Format:", self._format)
        export_form.addRow("File:", path_row)
        export_group = QGroupBox("Export", self)
        export_group.setLayout(export_form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(steps_group)
        layout.addLayout(cutoff_form)
        layout.addWidget(encoding_group)
        layout.addWidget(export_group)
        layout.addWidget(self._buttons)

        self._sync_enabled_state()

    # ---------------------------------------------------------------- helpers
    def _selected_format(self) -> ExportFormat:
        """Return the chosen export format as a real enum member."""
        return ExportFormat(self._format.currentData())

    def _sync_enabled_state(self) -> None:
        """Enable the export path controls only when exporting."""
        exporting = self._export.isChecked()
        self._format.setEnabled(exporting)
        self._path.setEnabled(exporting)
        self._browse.setEnabled(exporting)

    def _default_extension(self) -> str:
        """File extension for the current export format."""
        return ".sdf" if self._selected_format() == ExportFormat.SDF else ".csv"

    def _on_format_changed(self) -> None:
        """Re-suffix the current path when the format switches."""
        text = self._path.text().strip()
        if text:
            self._path.setText(str(Path(text).with_suffix(self._default_extension())))

    def _on_browse(self) -> None:
        """Pick an output file."""
        ext = self._default_extension()
        name = "batch_results" + ext
        filt = "CSV file (*.csv)" if ext == ".csv" else "SDF file (*.sdf)"
        filename, _ = QFileDialog.getSaveFileName(self, "Export Results", name, filt)
        if filename:
            self._path.setText(str(Path(filename).with_suffix(ext)))

    def _on_accept(self) -> None:
        """Validate before accepting: a step must be chosen and export needs a path."""
        config = self._build_config()
        if not config.has_any_step:
            self._path.setPlaceholderText("select at least one step or an export target")
            return
        if self._export.isChecked() and not self._path.text().strip():
            self._path.setPlaceholderText("an export file is required")
            return
        self.accept()

    def _build_config(self) -> BatchConfig:
        """Assemble a :class:`BatchConfig` from the current controls."""
        fp_options = self._fingerprint_options.options()
        export_path = None
        if self._export.isChecked() and self._path.text().strip():
            export_path = Path(self._path.text().strip()).with_suffix(self._default_extension())
        return BatchConfig(
            standardize=StandardizationOptions() if self._standardize.isChecked() else None,
            descriptors=self._descriptors.isChecked(),
            fingerprints=fp_options if self._fingerprints.isChecked() else None,
            scaffolds=self._scaffolds.isChecked(),
            cluster=(
                ClusterOptions(
                    method=ClusterMethod.BUTINA, fingerprint=fp_options, cutoff=self._cutoff.value()
                )
                if self._cluster.isChecked()
                else None
            ),
            export_path=export_path,
            export_format=self._selected_format(),
        )

    # ------------------------------------------------------------- public API
    def config(self) -> BatchConfig:
        """Return the configured pipeline."""
        return self._build_config()

    @staticmethod
    def get_config(parent: QWidget | None = None) -> BatchConfig | None:
        """Show the dialog modally; return the config, or ``None`` if cancelled."""
        dialog = BatchDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.config()
        return None
