"""Interactive Property Filter dock panel.

Displays min-max range numeric inputs (spinboxes) for all molecular descriptors
defined in ``DESCRIPTOR_SPECS``. Whenever the user updates any input value,
the panel triggers real-time row filtering on the molecule table.

Ranges are automatically updated and constrained to the actual min/max values
in the active dataset when molecules are loaded or descriptors are computed.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord

logger = logging.getLogger(__name__)


class PropertyFilterPanel(QWidget):
    """Dynamic range filter controls for all descriptors.

    Parameters
    ----------
    parent:
        Standard Qt parent.

    """

    #: Emitted with a dict mapping key.lower() -> (min, max) when ranges change.
    filters_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._records: list[MoleculeRecord] = []
        # key -> (label, min_widget, max_widget)
        self._widgets: dict[str, tuple[QLabel, QWidget, QWidget]] = {}
        self._updating = False

        self._placeholder = QLabel(
            "Load molecules and compute\ndescriptors to filter by property.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )

        # Form layout inside scroll area for all the descriptor range controls
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_content = QWidget(self._scroll)
        self._form = QFormLayout(scroll_content)
        self._form.setSpacing(8)
        self._form.setContentsMargins(10, 10, 10, 10)

        # Dynamically build controls for every registered descriptor spec
        for spec in DESCRIPTOR_SPECS:
            lbl = QLabel(f"<b>{spec.label}</b>", scroll_content)
            lbl.setToolTip(spec.tooltip)

            # Determine whether the value is an integer or float
            # (HBD, HBA, RotB, Rings, Lipinski are integers)
            is_int = spec.key in ("HBD", "HBA", "RotB", "Rings", "Lipinski")

            if is_int:
                w_min = QSpinBox(scroll_content)
                w_max = QSpinBox(scroll_content)
            else:
                w_min = QDoubleSpinBox(scroll_content)
                w_min.setDecimals(2)
                w_max = QDoubleSpinBox(scroll_content)
                w_max.setDecimals(2)

            for w in (w_min, w_max):
                w.setMinimumWidth(80)
                # Set initial loose range, updated dynamically on load
                w.setRange(-100000.0, 100000.0)

            # Connect changes to our filter trigger slot
            if is_int:
                w_min.valueChanged.connect(self._on_filter_changed)
                w_max.valueChanged.connect(self._on_filter_changed)
            else:
                w_min.valueChanged.connect(self._on_filter_changed)
                w_max.valueChanged.connect(self._on_filter_changed)

            row = QHBoxLayout()
            row.addWidget(w_min)
            row.addWidget(QLabel("to", scroll_content))
            row.addWidget(w_max)
            row.addStretch(1)

            self._form.addRow(lbl, row)
            self._widgets[spec.key.lower()] = (lbl, w_min, w_max)

        scroll_content.setLayout(self._form)
        self._scroll.setWidget(scroll_content)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(self._scroll)

        layout = QVBoxLayout(self)
        layout.addWidget(self._stack)

    # ------------------------------------------------------------- public API
    def update_ranges(self, records: list[MoleculeRecord]) -> None:
        """Scan the dataset to discover actual min/max descriptor boundaries."""
        self._records = records
        # Check if any molecules have computed descriptors
        has_descriptors = any(r.descriptors is not None for r in records)

        if not has_descriptors:
            self._stack.setCurrentWidget(self._placeholder)
            return

        self._updating = True
        try:
            for spec in DESCRIPTOR_SPECS:
                key = spec.key.lower()
                vals = [spec.getter(r.descriptors) for r in records if r.descriptors is not None]

                if not vals:
                    continue

                min_val = min(vals)
                max_val = max(vals)

                lbl, w_min, w_max = self._widgets[key]

                # Update widget ranges
                if isinstance(w_min, QSpinBox):
                    # Int ranges
                    w_min.setRange(int(min_val), int(max_val))
                    w_max.setRange(int(min_val), int(max_val))
                    w_min.setValue(int(min_val))
                    w_max.setValue(int(max_val))
                else:
                    # Float ranges (QDoubleSpinBox)
                    w_min.setRange(float(min_val), float(max_val))
                    w_max.setRange(float(min_val), float(max_val))
                    w_min.setValue(float(min_val))
                    w_max.setValue(float(max_val))

                if isinstance(w_min, QSpinBox):
                    lbl.setText(f"<b>{spec.label}</b> ({int(min_val)}–{int(max_val)})")
                else:
                    lbl.setText(f"<b>{spec.label}</b> ({min_val:.1f}–{max_val:.1f})")
        finally:
            self._updating = False

        self._stack.setCurrentWidget(self._scroll)
        # Trigger an initial filter notification (which is currently a no-op as min=min and max=max)
        self._on_filter_changed()

    def clear(self) -> None:
        """Reset controls and show placeholder page."""
        self._records.clear()
        self._stack.setCurrentWidget(self._placeholder)

    # --------------------------------------------------------------- handlers
    def _on_filter_changed(self) -> None:
        """Read all input spinbox values and emit the new active filter ranges."""
        if self._updating or not self._records:
            return

        active_ranges: dict[str, tuple[float, float]] = {}
        for key, (_, w_min, w_max) in self._widgets.items():
            if isinstance(w_min, QSpinBox):
                active_ranges[key] = (w_min.value(), w_max.value())
            else:
                active_ranges[key] = (w_min.value(), w_max.value())

        self.filters_changed.emit(active_ranges)
