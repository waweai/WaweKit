"""The Chemical Space panel: an interactive 2D scatter of the dataset.

Each point is a molecule, positioned by a projection of its fingerprint (see
:mod:`wawekit.services.chemistry.chemical_space`). The plot is a Matplotlib
figure embedded with ``FigureCanvasQTAgg``, which brings a real navigation
toolbar (pan, zoom, and **export to PNG/PDF/SVG**) for free — useful for a
research-grade tool.

Interaction, both directions:

* **Hover** a point → a tooltip with its name and the coloured value.
* **Click** a point, or **drag a lasso** around several → the panel emits
  :attr:`points_selected`, which the window turns into a table selection (so the
  Structure and Conformer panels follow too).
* **Table selection → plot**: :meth:`highlight_records` rings the selected points,
  updated in place so the current zoom is preserved.

Colour-by lets you paint points by any descriptor or the last similarity score,
turning the map into a property landscape. Missing values render grey, so an
un-computed descriptor is visibly absent rather than silently zero.
"""

from __future__ import annotations

import logging

import numpy as np
from matplotlib import colormaps
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.cm import ScalarMappable
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
from matplotlib.widgets import LassoSelector
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from wawekit.models.descriptors import DESCRIPTOR_BY_KEY, DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.chemical_space import ProjectionMethod, ProjectionResult

logger = logging.getLogger(__name__)

#: Colour-by choices that are not descriptors.
_COLOR_NONE = "None"
_COLOR_SIMILARITY = "Similarity"
_COLOR_CLUSTER = "Cluster"

#: Point sizes (unselected / selected) and the hover pixel radius.
_SIZE = 38
_SIZE_SELECTED = 96
_HOVER_RADIUS_PX = 12

#: Theme palettes: (figure/axes background, foreground, grid, missing-value grey).
_DARK = ("#1a1b1e", "#c8ccd2", "#2f3136", "#555b63")
_LIGHT = ("#ffffff", "#222222", "#dddddd", "#b8bcc2")


def _color_value(record: MoleculeRecord, key: str) -> float | None:
    """Return the numeric value used to colour ``record`` for dimension ``key``."""
    if key == _COLOR_SIMILARITY:
        return record.similarity.value if record.similarity is not None else None
    if key == _COLOR_CLUSTER:
        return None if record.cluster is None else float(record.cluster.cluster_id)
    spec = DESCRIPTOR_BY_KEY.get(key.lower())
    if spec is not None and record.descriptors is not None:
        return float(spec.getter(record.descriptors))
    return None


class ChemicalSpacePanel(QWidget):
    """Interactive 2D scatter of a chemical-space projection.

    Parameters
    ----------
    dark:
        Initial figure palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    #: Emitted with the list of MoleculeRecords the user picked (click or lasso).
    points_selected = Signal(object)

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = dark
        self._result: ProjectionResult | None = None
        self._xs = np.empty(0)
        self._ys = np.empty(0)
        self._selected_mask = np.zeros(0, dtype=bool)
        self._scatter = None
        self._annotation = None
        self._lasso: LassoSelector | None = None
        self._hover_index: int | None = None

        self._figure = Figure(figsize=(5, 4), tight_layout=True)
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)

        self._color_combo = QComboBox(self)
        self._color_combo.addItem(_COLOR_NONE)
        for spec in DESCRIPTOR_SPECS:
            self._color_combo.addItem(spec.label)
        self._color_combo.addItem(_COLOR_SIMILARITY)
        self._color_combo.addItem(_COLOR_CLUSTER)
        self._color_combo.currentIndexChanged.connect(self._render)

        controls = QHBoxLayout()
        controls.addWidget(self._toolbar, stretch=1)
        controls.addWidget(QLabel("Colour by:", self))
        controls.addWidget(self._color_combo)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._canvas, stretch=1)

        self._canvas.mpl_connect("pick_event", self._on_pick)
        self._canvas.mpl_connect("motion_notify_event", self._on_hover)
        self._render()

    # ------------------------------------------------------------- public API
    def set_projection(self, result: ProjectionResult) -> None:
        """Display a new projection, resetting any selection."""
        self._result = result
        self._xs = np.array([p.x for p in result.points], dtype=float)
        self._ys = np.array([p.y for p in result.points], dtype=float)
        self._selected_mask = np.zeros(len(result.points), dtype=bool)
        self._render()

    def clear(self) -> None:
        """Drop the projection (e.g. after the dataset is replaced)."""
        self._result = None
        self._xs = np.empty(0)
        self._ys = np.empty(0)
        self._selected_mask = np.zeros(0, dtype=bool)
        self._render()

    def highlight_records(self, records: list[MoleculeRecord]) -> None:
        """Ring the points backing ``records`` (table → plot), preserving zoom."""
        if self._result is None:
            return
        wanted = {id(r) for r in records}
        self._selected_mask = np.array(
            [id(p.record) in wanted for p in self._result.points], dtype=bool
        )
        self._apply_highlight()

    def set_dark(self, dark: bool) -> None:
        """Switch the figure palette to match the application theme."""
        if dark != self._dark:
            self._dark = dark
            self._render()

    # ---------------------------------------------------------------- render
    def _palette(self) -> tuple[str, str, str, str]:
        """Return (background, foreground, grid, missing-grey) for the theme."""
        return _DARK if self._dark else _LIGHT

    def _render(self) -> None:
        """Rebuild the whole figure from the current projection and colour-by."""
        bg, fg, grid, _grey = self._palette()
        self._figure.clear()
        self._figure.set_facecolor(bg)
        ax = self._figure.add_subplot(111)
        ax.set_facecolor(bg)
        for spine in ax.spines.values():
            spine.set_color(fg)
        ax.tick_params(colors=fg, labelsize=8)
        ax.grid(True, color=grid, linewidth=0.5)

        if self._result is None or not self._result.points:
            ax.text(
                0.5,
                0.5,
                "Run Chemistry → Chemical Space\nto project the dataset into 2D.",
                ha="center",
                va="center",
                color=fg,
                transform=ax.transAxes,
            )
            self._scatter = None
            self._lasso = None
            self._canvas.draw_idle()
            return

        colors, mappable = self._colors_for(self._color_combo.currentText())
        self._scatter = ax.scatter(
            self._xs,
            self._ys,
            c=colors,
            s=self._sizes(),
            edgecolors=self._edgecolors(),
            linewidths=1.4,
            picker=6,
        )
        if mappable is not None:
            bar = self._figure.colorbar(mappable, ax=ax)
            bar.ax.tick_params(colors=fg, labelsize=8)
            bar.set_label(self._color_combo.currentText(), color=fg)

        ax.set_title(self._title(), color=fg, fontsize=10)
        ax.set_xlabel(self._axis_label(0), color=fg, fontsize=8)
        ax.set_ylabel(self._axis_label(1), color=fg, fontsize=8)

        self._annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 12),
            textcoords="offset points",
            bbox={"boxstyle": "round", "fc": bg, "ec": fg, "alpha": 0.9},
            color=fg,
            fontsize=8,
            zorder=10,
        )
        self._annotation.set_visible(False)
        self._hover_index = None

        # LassoSelector is bound to the axes, so it is recreated on each render.
        self._lasso = LassoSelector(ax, onselect=self._on_lasso)
        self._canvas.draw_idle()

    def _sizes(self) -> np.ndarray:
        """Point sizes, larger for the currently highlighted rows."""
        return np.where(self._selected_mask, _SIZE_SELECTED, _SIZE)

    def _edgecolors(self):  # noqa: ANN202 — matplotlib colour list
        """Edge colours: ring the highlighted points, none for the rest."""
        _bg, fg, _grid, _grey = self._palette()
        return [fg if selected else "none" for selected in self._selected_mask]

    def _colors_for(self, key: str):  # noqa: ANN202 — (colours, mappable)
        """Return per-point colours and an optional colorbar mappable."""
        _bg, _fg, _grid, grey = self._palette()
        if key == _COLOR_NONE:
            return "#4f8cc9", None

        values = [_color_value(p.record, key) for p in self._result.points]
        present = [v for v in values if v is not None]
        if not present:
            # Nothing computed for this dimension yet: everything is unknown.
            return grey, None

        if key == _COLOR_CLUSTER:
            # Clusters are categories, not a scale — a qualitative palette keyed
            # by id (no colorbar) reads far better than a viridis gradient.
            cmap = colormaps["tab20"]
            colors = [cmap(int(v) % 20) if v is not None else grey for v in values]
            return colors, None

        norm = Normalize(vmin=min(present), vmax=max(present))
        cmap = colormaps["viridis"]
        colors = [cmap(norm(v)) if v is not None else grey for v in values]
        mappable = ScalarMappable(norm=norm, cmap=cmap)
        mappable.set_array([])
        return colors, mappable

    def set_color_by(self, key: str) -> None:
        """Select a colour-by dimension by name (e.g. after clustering)."""
        index = self._color_combo.findText(key)
        if index >= 0:
            self._color_combo.setCurrentIndex(index)  # triggers a re-render

    def _title(self) -> str:
        """Figure title: point count and, for PCA, captured variance."""
        result = self._result
        base = f"{result.method} · {result.n_points} molecule(s)"
        if result.explained_variance is not None:
            total = sum(result.explained_variance) * 100
            return f"{base} · {total:.0f}% variance shown"
        return base

    def _axis_label(self, axis: int) -> str:
        """Axis label: PCA reports per-axis variance; t-SNE axes are unitless."""
        result = self._result
        if result.method == ProjectionMethod.PCA and result.explained_variance is not None:
            pct = result.explained_variance[axis] * 100
            return f"PC{axis + 1} ({pct:.0f}%)"
        return f"t-SNE {axis + 1}"

    def _apply_highlight(self) -> None:
        """Update sizes/edges on the existing scatter without a full redraw."""
        if self._scatter is None:
            return
        self._scatter.set_sizes(self._sizes())
        self._scatter.set_edgecolors(self._edgecolors())
        self._canvas.draw_idle()

    # --------------------------------------------------------------- handlers
    def _on_pick(self, event) -> None:  # noqa: ANN001 — matplotlib event
        """Report the records behind a clicked point (or the few near it)."""
        if event.artist is not self._scatter or self._result is None:
            return
        records = [self._result.points[i].record for i in event.ind]
        if records:
            self.points_selected.emit(records)

    def _on_lasso(self, verts) -> None:  # noqa: ANN001 — list of (x, y)
        """Report every molecule enclosed by a lassoed region."""
        if self._result is None or len(verts) < 3:
            return  # a click, not a drag — handled by _on_pick
        path = MplPath(verts)
        inside = path.contains_points(np.column_stack([self._xs, self._ys]))
        records = [self._result.points[i].record for i in np.nonzero(inside)[0]]
        if records:
            self.points_selected.emit(records)

    def _on_hover(self, event) -> None:  # noqa: ANN001 — matplotlib event
        """Show a tooltip for the nearest point under the cursor."""
        if self._scatter is None or self._annotation is None or event.inaxes is None:
            self._hide_annotation()
            return
        ax = self._scatter.axes
        display = ax.transData.transform(np.column_stack([self._xs, self._ys]))
        distances = np.hypot(display[:, 0] - event.x, display[:, 1] - event.y)
        nearest = int(np.argmin(distances))
        if distances[nearest] > _HOVER_RADIUS_PX:
            self._hide_annotation()
            return
        if nearest == self._hover_index:
            return  # already showing this one
        self._hover_index = nearest
        point = self._result.points[nearest]
        key = self._color_combo.currentText()
        label = point.record.name
        value = _color_value(point.record, key)
        if value is not None:
            # Cluster ids are integers; everything else is a measured quantity.
            shown = f"{int(value)}" if key == _COLOR_CLUSTER else f"{value:.2f}"
            label += f"\n{key}: {shown}"
        self._annotation.xy = (point.x, point.y)
        self._annotation.set_text(label)
        self._annotation.set_visible(True)
        self._canvas.draw_idle()

    def _hide_annotation(self) -> None:
        """Hide the hover tooltip if it is showing."""
        if self._annotation is not None and self._annotation.get_visible():
            self._annotation.set_visible(False)
            self._hover_index = None
            self._canvas.draw_idle()
