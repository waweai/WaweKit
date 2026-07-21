"""Dialog for a substructure search.

One question — *which fragment?* — answered with live validation. The pattern
box parses on every keystroke and OK stays disabled until it is a valid query,
so a mistake is caught next to the box that caused it rather than after the
dialog closes (the same principle as the similarity dialog's SMILES box).

Parsing goes through :func:`~wawekit.services.chemistry.substructure.parse_query`,
so the dialog never imports RDKit — keeping ``gui -> services -> models -> core``
intact.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.substructure import SubstructureQuery
from wawekit.services.chemistry.substructure import parse_query


class SubstructureDialog(QDialog):
    """Choose a SMARTS/SMILES query pattern and whether to filter to matches."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Substructure Search")
        self.setModal(True)

        intro = QLabel(
            "Find molecules that contain a fragment. Matched atoms are highlighted\n"
            "in the thumbnails and the Structure panel.",
            self,
        )

        # --- query type (SMARTS is the query language; SMILES is read as one)
        self._smarts_radio = QRadioButton("SMARTS (query language)", self)
        self._smiles_radio = QRadioButton("SMILES", self)
        self._smarts_radio.setChecked(True)
        self._type_group = QButtonGroup(self)
        self._type_group.addButton(self._smarts_radio)
        self._type_group.addButton(self._smiles_radio)
        self._smarts_radio.toggled.connect(self._validate)
        type_box = QVBoxLayout()
        type_box.addWidget(self._smarts_radio)
        type_box.addWidget(self._smiles_radio)
        type_group = QGroupBox("Query type", self)
        type_group.setLayout(type_box)

        self._pattern = QLineEdit(self)
        self._pattern.setClearButtonEnabled(True)
        self._pattern.setPlaceholderText("e.g. c1ccncc1  or  [NX3][CX3](=O)  or  S(=O)(=O)N")
        self._pattern.textChanged.connect(self._validate)

        self._status = QLabel(self)
        self._status.setObjectName("queryStatus")
        self._status.setWordWrap(True)

        self._only_matches = QCheckBox("Show only matching molecules", self)
        self._only_matches.setChecked(True)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Search")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(type_group)
        layout.addWidget(QLabel("Pattern:", self))
        layout.addWidget(self._pattern)
        layout.addWidget(self._status)
        layout.addWidget(self._only_matches)
        layout.addWidget(self._buttons)

        self._validate()

    # ---------------------------------------------------------------- helpers
    def _is_smarts(self) -> bool:
        """Whether the pattern should be read as SMARTS (vs plain SMILES)."""
        return self._smarts_radio.isChecked()

    def _validate(self) -> None:
        """Parse the pattern on every keystroke and gate the Search button."""
        text = self._pattern.text().strip()
        query_mol = parse_query(text, self._is_smarts())
        if not text:
            self._status.setText("Enter a pattern to search for.")
        elif query_mol is None:
            kind = "SMARTS" if self._is_smarts() else "SMILES"
            self._status.setText(f"⚠ Not a valid {kind} pattern.")
        else:
            self._status.setText(f"✓ Valid query · {query_mol.GetNumAtoms()} atom(s)")
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(query_mol is not None)

    # ------------------------------------------------------------- public API
    def query(self) -> SubstructureQuery | None:
        """Return the configured query, or ``None`` if the pattern is invalid."""
        text = self._pattern.text().strip()
        if parse_query(text, self._is_smarts()) is None:
            return None
        return SubstructureQuery(pattern=text, is_smarts=self._is_smarts())

    def only_matches(self) -> bool:
        """Whether the table should be filtered to matching molecules."""
        return self._only_matches.isChecked()

    @staticmethod
    def get_query(parent: QWidget | None = None) -> tuple[SubstructureQuery, bool] | None:
        """Show the dialog; return ``(query, only_matches)`` or ``None`` if cancelled."""
        dialog = SubstructureDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            query = dialog.query()
            if query is not None:
                return query, dialog.only_matches()
        return None
