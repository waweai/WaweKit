"""The Convert Format dialog.

Lets the user pick an input molecule file, choose an output format, and convert.
Preview summary shows how many molecules were found before committing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from wawekit.services.io.converter import (
    FORMAT_EXTENSIONS,
    OUTPUT_FORMATS,
    ConversionReport,
    convert_file,
)
from wawekit.services.io.molecule_loader import (
    SUPPORTED_EXTENSIONS,
    file_dialog_filter,
)

logger = logging.getLogger(__name__)


class ConverterDialog(QDialog):
    """File-format conversion dialog.

    Parameters
    ----------
    parent:
        Standard Qt parent widget.

    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert File Format")
        self.setModal(True)
        self.setMinimumWidth(520)

        # Input file row
        self._input_edit = QLineEdit(self)
        self._input_edit.setReadOnly(True)
        self._input_edit.setPlaceholderText("Select an input file…")
        self._input_browse = QPushButton("Browse…", self)
        self._input_browse.clicked.connect(self._on_browse_input)

        input_row = QHBoxLayout()
        input_row.addWidget(self._input_edit, stretch=1)
        input_row.addWidget(self._input_browse)

        # Output format
        self._format_combo = QComboBox(self)
        for key, label in OUTPUT_FORMATS.items():
            self._format_combo.addItem(label, key)

        # Output file row
        self._output_edit = QLineEdit(self)
        self._output_edit.setReadOnly(True)
        self._output_edit.setPlaceholderText("Output file path…")
        self._output_browse = QPushButton("Browse…", self)
        self._output_browse.clicked.connect(self._on_browse_output)

        output_row = QHBoxLayout()
        output_row.addWidget(self._output_edit, stretch=1)
        output_row.addWidget(self._output_browse)

        # Status/preview label
        self._status_label = QLabel("", self)
        self._status_label.setWordWrap(True)

        # Buttons
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Convert")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self._on_convert)
        self._buttons.rejected.connect(self.reject)

        # Auto-update output path when format changes
        self._format_combo.currentIndexChanged.connect(self._update_output_path)

        # Layout
        form = QFormLayout()
        form.addRow("Input file:", input_row)
        form.addRow("Output format:", self._format_combo)
        form.addRow("Output file:", output_row)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._status_label)
        layout.addWidget(self._buttons)

    # --------------------------------------------------------------- handlers
    def _on_browse_input(self) -> None:
        """Pick an input molecule file."""
        filename, _ = QFileDialog.getOpenFileName(
            self, "Select Input File", "", file_dialog_filter()
        )
        if not filename:
            return
        self._input_edit.setText(filename)
        self._update_output_path()
        self._validate()

    def _on_browse_output(self) -> None:
        """Pick an output file location."""
        fmt = self._format_combo.currentData()
        ext = FORMAT_EXTENSIONS.get(fmt, ".sdf")
        label = OUTPUT_FORMATS.get(fmt, f"Files (*{ext})")
        filename, _ = QFileDialog.getSaveFileName(
            self, "Select Output File", self._output_edit.text() or "", label
        )
        if filename:
            self._output_edit.setText(filename)
            self._validate()

    def _update_output_path(self) -> None:
        """Auto-suggest an output path based on input path and chosen format."""
        input_text = self._input_edit.text()
        if not input_text:
            return
        fmt = self._format_combo.currentData()
        ext = FORMAT_EXTENSIONS.get(fmt, ".sdf")
        input_path = Path(input_text)
        suggested = input_path.with_stem(input_path.stem + "_converted").with_suffix(ext)
        self._output_edit.setText(str(suggested))
        self._validate()

    def _validate(self) -> None:
        """Check if both input and output are set and enable the Convert button."""
        input_ok = bool(self._input_edit.text()) and Path(self._input_edit.text()).is_file()
        output_ok = bool(self._output_edit.text())

        if input_ok:
            ext = Path(self._input_edit.text()).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                fmt_name = SUPPORTED_EXTENSIONS[ext].upper()
                self._status_label.setText(
                    f"Input detected as <b>{fmt_name}</b> format. "
                    f"Ready to convert to <b>{self._format_combo.currentText()}</b>."
                )
            else:
                self._status_label.setText(f"Unsupported input extension: {ext}")
                input_ok = False
        else:
            self._status_label.setText("")

        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(input_ok and output_ok)

    def _on_convert(self) -> None:
        """Run the conversion and show results."""
        input_path = Path(self._input_edit.text())
        output_path = Path(self._output_edit.text())
        output_format = self._format_combo.currentData()

        self._status_label.setText("Converting…")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        # Run synchronously (conversions are fast for typical file sizes).
        report: ConversionReport = convert_file(input_path, output_path, output_format)

        if report.ok:
            msg = (
                f"Successfully converted {report.n_read} molecule(s) from "
                f"<b>{input_path.name}</b> → <b>{output_path.name}</b>."
            )
            if report.n_written < report.n_read:
                msg += f"<br/>{report.n_written} written (format limitation)."
            if report.errors:
                msg += f"<br/>{len(report.errors)} warning(s)."
            self._status_label.setText(msg)
            QMessageBox.information(
                self,
                "Conversion Complete",
                f"Converted {report.n_written} molecule(s) to {output_path.name}.\n"
                + ("\n".join(report.errors) if report.errors else ""),
            )
            self.accept()
        else:
            error_text = "\n".join(report.errors) if report.errors else "Unknown error."
            self._status_label.setText("<span style='color: red;'>Conversion failed.</span>")
            QMessageBox.warning(self, "Conversion Failed", error_text)
            self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)

    # -------------------------------------------------------------- class API
    @staticmethod
    def run_converter(parent: QWidget | None = None) -> None:
        """Show the converter dialog modally."""
        dialog = ConverterDialog(parent)
        dialog.exec()
