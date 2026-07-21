"""Options dialog for fingerprint computation.

Follows :class:`~wawekit.gui.dialogs.standardize_dialog.StandardizeDialog`: a
focused :class:`~PySide6.QtWidgets.QDialog` plus the *static factory*
:meth:`FingerprintDialog.get_options`, the idiom Qt itself uses
(``QFileDialog.getOpenFileNames``). Callers get ready options or ``None``.

Module 7 moved the controls themselves into
:class:`~wawekit.gui.widgets.fingerprint_options.FingerprintOptionsWidget` so
the similarity dialog could offer the identical choices. What is left here is
what a *dialog* is actually for: framing the controls with an explanation, and
turning OK/Cancel into a return value. That is a healthy amount for a dialog to
weigh.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from wawekit.gui.widgets.fingerprint_options import FingerprintOptionsWidget
from wawekit.models.fingerprints import FingerprintOptions


class FingerprintDialog(QDialog):
    """Lets the user choose the fingerprint algorithm and its parameters."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compute Fingerprints")
        self.setModal(True)

        intro = QLabel(
            "Fingerprints encode each structure as a bit vector, enabling\n"
            "similarity search and clustering.",
            self,
        )

        self._options = FingerprintOptionsWidget(self)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addWidget(self._options)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    # ------------------------------------------------------------- public API
    def options(self) -> FingerprintOptions:
        """Build an options object from the current widget states."""
        return self._options.options()

    @staticmethod
    def get_options(parent: QWidget | None = None) -> FingerprintOptions | None:
        """Show the dialog modally; return options, or ``None`` if cancelled."""
        dialog = FingerprintDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options()
        return None
