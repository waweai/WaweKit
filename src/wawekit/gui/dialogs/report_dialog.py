"""Dialog to configure a report.

Pick a title, the format(s), whether to draw structures, and where to write. The
output field is a *base* path; each chosen format appends its own suffix, so one
"Generate" can produce ``results.html`` and ``results.pdf`` side by side.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wawekit.services.reporting import ReportConfig, ReportFormat


class ReportDialog(QDialog):
    """Assemble a :class:`~wawekit.services.reporting.ReportConfig`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate Report")
        self.setModal(True)

        self._title = QLineEdit("Wawekit Report", self)

        self._html = QCheckBox("HTML (opens in a browser, prints to PDF)", self)
        self._html.setChecked(True)
        self._pdf = QCheckBox("PDF (paginated, print-ready)", self)
        self._pdf.setChecked(True)
        self._html.toggled.connect(self._sync_ok)
        self._pdf.toggled.connect(self._sync_ok)

        self._depictions = QCheckBox("Include 2D structure depictions", self)
        self._depictions.setChecked(True)

        self._max = QSpinBox(self)
        self._max.setRange(1, 5000)
        self._max.setValue(ReportConfig().max_molecules)
        self._max.setToolTip("Cap on molecules shown; the summary still covers the whole dataset.")

        self._path = QLineEdit(self)
        self._path.setPlaceholderText("choose a base output path…")
        self._path.textChanged.connect(self._sync_ok)
        browse = QPushButton("Browse…", self)
        browse.clicked.connect(self._on_browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self._path, stretch=1)
        path_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("Title:", self._title)
        form.addRow("HTML:", self._html)
        form.addRow("PDF:", self._pdf)
        form.addRow(self._depictions)
        form.addRow("Max molecules shown:", self._max)
        form.addRow("Output:", path_row)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Generate")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._buttons)
        self._sync_ok()

    # ---------------------------------------------------------------- helpers
    def _formats(self) -> tuple[ReportFormat, ...]:
        """Return the chosen formats."""
        chosen = []
        if self._html.isChecked():
            chosen.append(ReportFormat.HTML)
        if self._pdf.isChecked():
            chosen.append(ReportFormat.PDF)
        return tuple(chosen)

    def _sync_ok(self) -> None:
        """Enable Generate only with a format chosen and a path set."""
        ok = bool(self._formats()) and bool(self._path.text().strip())
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _on_browse(self) -> None:
        """Pick a base output path (extension is added per format)."""
        filename, _ = QFileDialog.getSaveFileName(self, "Report Output", "wawekit_report")
        if filename:
            # Strip any extension the user typed — formats add their own.
            self._path.setText(str(Path(filename).with_suffix("")))

    # ------------------------------------------------------------- public API
    def config(self) -> ReportConfig:
        """Build the report configuration from the current controls."""
        return ReportConfig(
            title=self._title.text().strip() or "Wawekit Report",
            output_path=Path(self._path.text().strip()).with_suffix(""),
            formats=self._formats(),
            max_molecules=self._max.value(),
            include_depictions=self._depictions.isChecked(),
        )

    @staticmethod
    def get_config(parent: QWidget | None = None) -> ReportConfig | None:
        """Show the dialog modally; return the config, or ``None`` if cancelled."""
        dialog = ReportDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.config()
        return None
