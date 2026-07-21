"""The Reproducibility panel: results of a standardization-divergence audit.

Shows the three numbers a dataset-reproducibility check needs: the headline
score (per identity convention), a protocol-pair agreement heatmap, and a cause
spectrum bar chart — plus a list of labile molecules so a curator can inspect
exactly which structures are pipeline-dependent and why.

Built on the same Matplotlib-embedding pattern as the Chemical Space panel
(Module 10): a real navigation toolbar, so the heatmap/chart export to
PNG/PDF/SVG for a paper's figures for free.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from wawekit.services.reproducibility import (
    DivergenceRun,
    MoleculeDivergence,
    ReproducibilityMetrics,
)

#: Palette: (figure background, foreground text, grid).
_DARK = ("#1a1b1e", "#c8ccd2", "#2f3136")
_LIGHT = ("#ffffff", "#222222", "#dddddd")

#: Item-data role carrying the MoleculeDivergence behind each list row.
_RESULT_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ReproducibilityPanel(QWidget):
    """Displays a completed divergence run: scores, heatmap, causes, molecules.

    Parameters
    ----------
    dark:
        Initial figure palette; switchable at runtime via :meth:`set_dark`.
    parent:
        Standard Qt parent.

    """

    #: Emitted with the molecule name of a clicked labile-molecule row.
    molecule_selected = Signal(str)

    def __init__(self, dark: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = dark
        self._run: DivergenceRun | None = None
        self._metrics: ReproducibilityMetrics | None = None

        self._headline = QLabel("", self)
        self._headline.setWordWrap(True)
        self._headline.setObjectName("reproHeadline")

        self._heatmap_figure = Figure(figsize=(4.5, 3.5), tight_layout=True)
        self._heatmap_canvas = FigureCanvasQTAgg(self._heatmap_figure)
        self._spectrum_figure = Figure(figsize=(4.5, 3.5), tight_layout=True)
        self._spectrum_canvas = FigureCanvasQTAgg(self._spectrum_figure)

        charts = QHBoxLayout()
        charts.addWidget(self._heatmap_canvas)
        charts.addWidget(self._spectrum_canvas)
        charts_widget = QWidget(self)
        charts_widget.setLayout(charts)

        self._labile_list = QListWidget(self)
        self._labile_list.itemSelectionChanged.connect(self._on_selection_changed)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(charts_widget)
        splitter.addWidget(self._labile_list)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._placeholder = QLabel(
            "Run a standardization-reproducibility audit to see results here.\n"
            "(Research → Reproducibility Audit…, Ctrl+Shift+R)",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._placeholder)
        self._stack.addWidget(splitter)

        layout = QVBoxLayout(self)
        layout.addWidget(self._headline)
        layout.addWidget(self._stack, stretch=1)

    # ------------------------------------------------------------- public API
    def set_results(self, run: DivergenceRun, metrics: ReproducibilityMetrics) -> None:
        """Display a completed divergence run and its metrics."""
        self._run = run
        self._metrics = metrics
        self._render()
        self._stack.setCurrentIndex(1)

    def clear(self) -> None:
        """Drop the current results (e.g. after the dataset changes)."""
        self._run = None
        self._metrics = None
        self._headline.setText("")
        self._labile_list.clear()
        self._stack.setCurrentIndex(0)

    def set_dark(self, dark: bool) -> None:
        """Switch the figure palette to match the application theme."""
        if dark != self._dark:
            self._dark = dark
            if self._run is not None:
                self._render()

    # ---------------------------------------------------------------- render
    def _palette(self) -> tuple[str, str, str]:
        return _DARK if self._dark else _LIGHT

    def _render(self) -> None:
        """Rebuild the headline, both charts, and the labile-molecule list."""
        assert self._run is not None and self._metrics is not None
        run, metrics = self._run, self._metrics

        failures = f", {metrics.n_with_failures} with failures" if metrics.n_with_failures else ""
        self._headline.setText(
            f"<b>{metrics.n_molecules}</b> molecule(s) audited across "
            f"<b>{len(run.protocols)}</b> protocol(s) — "
            f"SMILES-reproducibility <b>{metrics.smiles_reproducibility:.0%}</b>, "
            f"InChIKey-reproducibility <b>{metrics.inchikey_reproducibility:.0%}</b> "
            f"({metrics.n_labile} labile{failures})."
        )
        self._render_heatmap()
        self._render_spectrum()
        self._render_labile_list()

    def _render_heatmap(self) -> None:
        """Draw the protocol-pair agreement heatmap (InChIKey agreement)."""
        bg, fg, _grid = self._palette()
        self._heatmap_figure.clear()
        self._heatmap_figure.set_facecolor(bg)
        ax = self._heatmap_figure.add_subplot(111)
        ax.set_facecolor(bg)

        run = self._run
        assert run is not None
        names = [p.name for p in run.protocols]
        n = len(names)
        matrix = np.ones((n, n))
        for pair in self._metrics.pairwise if self._metrics else []:
            i, j = names.index(pair.protocol_a), names.index(pair.protocol_b)
            matrix[i, j] = matrix[j, i] = pair.inchikey_agreement

        # Agreement is a SEQUENTIAL quantity (0 → 1), so it gets a single-hue
        # light→dark ramp. The obvious-looking "RdYlGn" is wrong twice over: it
        # is a diverging ramp applied to non-diverging data (implying a
        # meaningful midpoint that does not exist), and red-green is the classic
        # failure case for colour-vision deficiency (~8% of men). `viridis` is
        # perceptually uniform, CVD-safe, and legible in greyscale print —
        # which matters because this panel's charts are exported as paper
        # figures.
        im = ax.imshow(matrix, vmin=0, vmax=1, cmap="viridis")
        ax.set_xticks(range(n))
        ax.set_yticks(range(n))
        ax.set_xticklabels(names, color=fg, fontsize=8, rotation=30, ha="right")
        ax.set_yticklabels(names, color=fg, fontsize=8)
        for i in range(n):
            for j in range(n):
                # Annotate every cell so the value is never encoded by colour
                # alone; flip the text between white and near-black against the
                # cell's own lightness so it stays readable at both ramp ends.
                value = matrix[i, j]
                ax.text(
                    j,
                    i,
                    f"{value:.0%}",
                    ha="center",
                    va="center",
                    color="white" if value < 0.6 else "#101010",
                    fontsize=8,
                )
        ax.set_title("Protocol agreement (InChIKey)", color=fg, fontsize=10)
        bar = self._heatmap_figure.colorbar(im, ax=ax, fraction=0.046)
        bar.ax.tick_params(colors=fg, labelsize=7)
        self._heatmap_canvas.draw_idle()

    def _render_spectrum(self) -> None:
        """Draw the cause-attribution bar chart."""
        bg, fg, grid = self._palette()
        self._spectrum_figure.clear()
        self._spectrum_figure.set_facecolor(bg)
        ax = self._spectrum_figure.add_subplot(111)
        ax.set_facecolor(bg)
        ax.grid(True, axis="x", color=grid, linewidth=0.5)

        spectrum = self._metrics.cause_spectrum if self._metrics else {}
        if spectrum:
            items = sorted(spectrum.items(), key=lambda kv: kv[1], reverse=True)
            labels = [op.value.replace("_", " ") for op, _ in items]
            values = [v for _, v in items]
            ax.barh(labels, values, color="#e0724f")
            ax.set_xlim(0, 1)
            ax.tick_params(colors=fg, labelsize=8)
            ax.set_xlabel("Fraction of labile molecules", color=fg, fontsize=8)
        else:
            ax.text(
                0.5,
                0.5,
                "No divergent molecules",
                ha="center",
                va="center",
                color=fg,
                transform=ax.transAxes,
            )
        ax.set_title("Divergence cause spectrum", color=fg, fontsize=10)
        for spine in ax.spines.values():
            spine.set_color(fg)
        self._spectrum_canvas.draw_idle()

    def _render_labile_list(self) -> None:
        """Populate the list of labile molecules, worst-agreement first."""
        self._labile_list.clear()
        run = self._run
        assert run is not None
        labile = [r for r in run.results if r.is_labile]
        labile.sort(key=lambda r: (r.smiles_agree, r.inchikey_agree))
        for result in labile:
            causes = ", ".join(op.value for op in result.causes) or "unattributed"
            item = QListWidgetItem(
                f"{result.name}  —  {result.n_distinct_smiles} SMILES form(s), "
                f"{result.n_distinct_inchikeys} InChIKey form(s)  —  cause: {causes}"
            )
            item.setData(_RESULT_ROLE, result)
            self._labile_list.addItem(item)

    def _on_selection_changed(self) -> None:
        """Emit the name of the selected labile molecule."""
        items = self._labile_list.selectedItems()
        if not items:
            return
        result: MoleculeDivergence = items[0].data(_RESULT_ROLE)
        self.molecule_selected.emit(result.name)
