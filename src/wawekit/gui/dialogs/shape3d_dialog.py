"""Options dialog for 3D shape and radial-shell descriptors.

Follows the same static-factory idiom as the other option dialogs
(:meth:`Shape3DDialog.get_options` returns options or ``None`` on cancel), with
one addition: because these descriptors need 3D geometry that a freshly loaded
dataset does not have, the dialog also offers to generate it, and returns both
option objects together.

The shell radii are entered as free text rather than a pair of spin boxes: two
shells is only the published default, and a user exploring core-versus-rim
composition wants three or four without the dialog dictating how many.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.conformers import ConformerOptions
from wawekit.models.shape3d import (
    CenterMode,
    ConformerChoice,
    RadialOptions,
    ShellNormalization,
)


def parse_shells(text: str) -> tuple[float, ...]:
    """Parse a comma/space separated list of shell radii.

    Parameters
    ----------
    text:
        User input, e.g. ``"3, 6"`` or ``"2 4 6"``.

    Returns
    -------
    tuple
        The radii, in the order given.

    Raises
    ------
    ValueError
        If a token is not a number, or nothing parses. Ordering and positivity
        are left to :class:`~wawekit.models.shape3d.RadialOptions`, which
        already enforces them — validating twice would let the two rules drift.

    """
    tokens = [token for token in text.replace(",", " ").split() if token]
    if not tokens:
        raise ValueError("enter at least one shell radius")
    try:
        return tuple(float(token) for token in tokens)
    except ValueError as exc:
        raise ValueError(f"'{text}' is not a list of numbers") from exc


class Shape3DDialog(QDialog):
    """Lets the user configure 3D shape descriptors before they run."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("3D Shape Descriptors")
        self.setModal(True)

        defaults = RadialOptions()

        intro = QLabel(
            "Measure 3D shape (plane of best fit, radius of gyration, rod/disc/sphere)\n"
            "and radial shell composition — what chemistry sits near the core versus\n"
            "the rim. Runs on your selection, or the whole dataset if nothing is\n"
            "selected.",
            self,
        )

        self._shells = QLineEdit(", ".join(f"{r:g}" for r in defaults.shells), self)
        self._shells.setToolTip("Shell radii in ångström, increasing — e.g. '3, 6'")

        self._center = QComboBox(self)
        for mode in CenterMode:
            self._center.addItem(mode.label, mode)
        self._center.setCurrentIndex(list(CenterMode).index(defaults.center))

        self._normalization = QComboBox(self)
        for norm in ShellNormalization:
            self._normalization.addItem(str(norm), norm)
        self._normalization.setCurrentIndex(list(ShellNormalization).index(defaults.normalization))

        self._conformer = QComboBox(self)
        for choice in ConformerChoice:
            self._conformer.addItem(str(choice), choice)
        self._conformer.setCurrentIndex(list(ConformerChoice).index(defaults.conformer))

        self._cumulative = QCheckBox("Cumulative shells (nested, not annular)", self)
        self._cumulative.setChecked(defaults.cumulative)
        self._cumulative.setToolTip(
            "On: each shell counts every atom within that radius (the published\n"
            "convention). Off: each shell counts only atoms between it and the\n"
            "previous radius, separating core composition from rim composition."
        )

        self._include_h = QCheckBox("Include hydrogens", self)
        self._include_h.setChecked(defaults.include_hydrogens)
        self._include_h.setToolTip(
            "Affects the radial shells only. Whole-molecule shape descriptors are\n"
            "always measured on the full hydrogen-bearing geometry."
        )

        self._generate = QCheckBox("Generate 3D conformers for molecules that lack them", self)
        self._generate.setChecked(True)
        self._generate.setToolTip(
            "These descriptors need 3D geometry. Embedding is far slower than\n"
            "measuring, so turn this off to measure only what is already generated."
        )

        self._n_confs = QSpinBox(self)
        self._n_confs.setRange(1, 500)
        self._n_confs.setValue(ConformerOptions().n_confs)
        self._generate.toggled.connect(self._n_confs.setEnabled)

        form = QFormLayout()
        form.addRow("Shell radii (Å):", self._shells)
        form.addRow("Measure from:", self._center)
        form.addRow("Normalise:", self._normalization)
        form.addRow("Conformer:", self._conformer)
        form.addRow("", self._cumulative)
        form.addRow("", self._include_h)
        form.addRow("", self._generate)
        form.addRow("Conformers each:", self._n_confs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        """Validate the shell radii before closing, so errors stay in context.

        Rejecting here rather than at the call site means the user fixes a typo
        in the field they typed it into, with the rest of their choices intact.
        """
        try:
            self.options()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid shell radii", str(exc))
            self._shells.setFocus()
            self._shells.selectAll()
            return
        self.accept()

    def options(self) -> RadialOptions:
        """Build a radial options object from the current control values.

        Raises
        ------
        ValueError
            If the shell radii are unparseable, non-positive or out of order.

        """
        return RadialOptions(
            shells=parse_shells(self._shells.text()),
            center=self._center.currentData(),
            normalization=self._normalization.currentData(),
            conformer=self._conformer.currentData(),
            cumulative=self._cumulative.isChecked(),
            include_hydrogens=self._include_h.isChecked(),
        )

    def conformer_options(self) -> ConformerOptions | None:
        """Conformer settings for molecules lacking geometry, or ``None`` to skip."""
        if not self._generate.isChecked():
            return None
        return ConformerOptions(n_confs=self._n_confs.value())

    @staticmethod
    def get_options(
        parent: QWidget | None = None,
    ) -> tuple[RadialOptions, ConformerOptions | None] | None:
        """Show the dialog modally.

        Returns
        -------
        tuple or None
            ``(radial options, conformer options or None)``, or ``None`` if the
            user cancelled.

        """
        dialog = Shape3DDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.options(), dialog.conformer_options()
        return None
