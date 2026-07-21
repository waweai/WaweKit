"""Options dialog for the standardization pipeline.

A small, focused :class:`~PySide6.QtWidgets.QDialog` exposing one checkbox per
pipeline step. The *static factory* pattern (:meth:`StandardizeDialog.get_options`)
is the idiom Qt itself uses (``QFileDialog.getOpenFileNames`` etc.): callers get
either a ready :class:`StandardizationOptions` or ``None`` on cancel, without
managing dialog lifetime themselves.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from wawekit.services.chemistry.standardizer import StandardizationOptions


class StandardizeDialog(QDialog):
    """Lets the user compose the standardization pipeline before running it."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Standardize Molecules")
        self.setModal(True)

        intro = QLabel(
            "Select the standardization steps to apply.\n"
            "A full report of every change will be shown afterwards.",
            self,
        )

        defaults = StandardizationOptions()
        self._cleanup = QCheckBox("Cleanup (sanitize, normalize functional groups)", self)
        self._cleanup.setChecked(defaults.cleanup)
        self._strip = QCheckBox("Strip salts && solvents (keep largest fragment)", self)
        self._strip.setChecked(defaults.strip_salts)
        self._neutralize = QCheckBox("Neutralize charges", self)
        self._neutralize.setChecked(defaults.neutralize)
        self._tautomer = QCheckBox("Canonicalize tautomers (slower on large sets)", self)
        self._tautomer.setChecked(defaults.canonicalize_tautomer)
        self._dedup = QCheckBox("Remove duplicates (by standardized structure)", self)
        self._dedup.setChecked(defaults.remove_duplicates)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        for box in (self._cleanup, self._strip, self._neutralize, self._tautomer, self._dedup):
            layout.addWidget(box)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def options(self) -> StandardizationOptions:
        """Build an options object from the current checkbox states."""
        return StandardizationOptions(
            cleanup=self._cleanup.isChecked(),
            strip_salts=self._strip.isChecked(),
            neutralize=self._neutralize.isChecked(),
            canonicalize_tautomer=self._tautomer.isChecked(),
            remove_duplicates=self._dedup.isChecked(),
        )

    @staticmethod
    def get_options(parent: QWidget | None = None) -> StandardizationOptions | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = StandardizeDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options()
        return None
