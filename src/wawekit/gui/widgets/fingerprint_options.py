"""Reusable control group for choosing fingerprint options.

Why this is a widget and not part of a dialog
----------------------------------------------
In Module 6 these controls lived inside
:class:`~wawekit.gui.dialogs.fingerprint_dialog.FingerprintDialog`, and that was
right: there was exactly one consumer, and a widget invented for a single caller
is an abstraction you pay for and don't use.

Module 7 brings the second consumer. A similarity search has to encode the query
and the dataset the *same* way (see
:mod:`wawekit.services.chemistry.similarity`), so its dialog must offer the same
choices. Copying the controls would mean two enable/disable rules to keep in
step and — more expensively — two places for the ``QVariant`` coercion below to
be forgotten. That's the moment to extract: when the duplication is real and
present, not when it is imagined.

The widget owns the whole rule "which parameters mean something for which
algorithm", so any dialog that embeds it gets that behaviour for free.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.fingerprints import (
    BIT_SIZE_CHOICES,
    FingerprintKind,
    FingerprintOptions,
)

#: Explanatory one-liners shown under the selector, per algorithm.
_KIND_HELP = {
    FingerprintKind.MORGAN: (
        "Circular fragments around each atom (ECFP). The standard choice for similarity."
    ),
    FingerprintKind.MACCS: (
        "166 predefined structural keys. Fixed size, no parameters, interpretable bits."
    ),
    FingerprintKind.RDKIT: "Daylight-style paths through the molecule, hashed into bits.",
}


class FingerprintOptionsWidget(QWidget):
    """Algorithm selector plus the parameters that algorithm actually uses.

    The controls **depend on each other**: radius and features apply only to
    Morgan, bit size to Morgan and RDKit, and MACCS takes no parameters at all.
    Rather than let users set values that are silently ignored, the kind
    selector drives an enable/disable pass (``currentIndexChanged`` →
    :meth:`_sync_enabled_state`), so the widget can only express option sets
    that mean something.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        defaults = FingerprintOptions()

        self._kind = QComboBox(self)
        for kind in FingerprintKind:
            # Store the enum itself as item data — see _selected_kind for what
            # Qt does to it on the way back out.
            self._kind.addItem(str(kind), kind)
        self._kind.setCurrentIndex(self._kind.findData(defaults.kind))
        self._kind.currentIndexChanged.connect(self._sync_enabled_state)

        self._help = QLabel(self)
        self._help.setWordWrap(True)
        self._help.setObjectName("fingerprintHelp")

        self._radius = QSpinBox(self)
        self._radius.setRange(1, 6)
        self._radius.setValue(defaults.radius)
        self._radius.setToolTip("Bonds out from each atom. 2 is the usual default (ECFP4).")

        self._bits = QComboBox(self)
        for size in BIT_SIZE_CHOICES:
            self._bits.addItem(f"{size} bits", size)
        self._bits.setCurrentIndex(self._bits.findData(defaults.n_bits))
        self._bits.setToolTip("More bits mean fewer collisions, at the cost of memory.")

        self._features = QCheckBox("Use pharmacophoric features (FCFP instead of ECFP)", self)
        self._features.setChecked(defaults.use_features)
        self._features.setToolTip(
            "Match by atom role (donor/acceptor/aromatic) rather than exact element."
        )

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.addRow("Algorithm:", self._kind)
        form.addRow("Radius:", self._radius)
        form.addRow("Bit size:", self._bits)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(form)
        layout.addWidget(self._help)
        layout.addWidget(self._features)

        self._sync_enabled_state()

    # ---------------------------------------------------------------- helpers
    def _selected_kind(self) -> FingerprintKind:
        """Return the algorithm currently chosen in the selector.

        **Qt gotcha, learned the hard way in Module 6.**
        :class:`~wawekit.models.fingerprints.FingerprintKind` is a
        :class:`~enum.StrEnum`, so the member handed to ``addItem`` is also a
        ``str``. Qt stores item data in a ``QVariant``, which converts it — and
        ``currentData()`` hands back a *plain* ``str``, not the enum member.
        Every ``is`` check against it then silently returns ``False``
        (``"MACCS" is FingerprintKind.MACCS`` → ``False``), which made the
        Module 6 dialog build Morgan options whatever the user picked.

        Coercing through the enum's constructor restores a real member, so
        callers get the type the annotation promises. Keeping this in one
        widget is now the reason it can't be forgotten in the next dialog.
        """
        return FingerprintKind(self._kind.currentData())

    def _sync_enabled_state(self) -> None:
        """Enable only the parameters that affect the selected algorithm."""
        kind = self._selected_kind()
        is_morgan = kind is FingerprintKind.MORGAN
        self._radius.setEnabled(is_morgan)
        self._features.setEnabled(is_morgan)
        self._bits.setEnabled(kind is not FingerprintKind.MACCS)
        self._help.setText(_KIND_HELP[kind])

    # ------------------------------------------------------------- public API
    def options(self) -> FingerprintOptions:
        """Build an options object from the current widget states."""
        return FingerprintOptions(
            kind=self._selected_kind(),
            radius=self._radius.value(),
            n_bits=self._bits.currentData(),
            use_features=self._features.isChecked(),
        )

    def set_options(self, options: FingerprintOptions) -> None:
        """Load ``options`` into the controls.

        Lets a caller open the widget on the settings already in use rather than
        on the defaults — which is what Module 7's similarity dialog wants, so
        a second search doesn't silently re-encode the dataset a new way.
        """
        self._kind.setCurrentIndex(self._kind.findData(FingerprintKind(options.kind)))
        self._radius.setValue(options.radius)
        bits_index = self._bits.findData(options.n_bits)
        if bits_index >= 0:
            # A normalized MACCS options object reports 167 bits, which is not
            # one of the offered sizes; leaving the combo alone is correct
            # there, since the value is ignored for MACCS anyway.
            self._bits.setCurrentIndex(bits_index)
        self._features.setChecked(options.use_features)
        self._sync_enabled_state()
