"""The application's main window (the desktop shell).

Module 2 turns the empty shell into a working tool: users open molecule files
via *File → Open* or by dragging them onto the window; parsing runs on a
background thread with a progress bar; results land in the molecule table and
the Workspace dock lists every loaded file.

Design notes
------------
* The window receives its collaborators (config, theme manager) through the
  constructor (*dependency injection*) instead of reaching for globals.
* File loads are queued and processed **one at a time** so the progress bar is
  always meaningful; dropping five files simply enqueues five loads.
* All RDKit work happens in :func:`~wawekit.services.io.molecule_loader.load_file`
  running inside a :class:`~wawekit.services.workers.FunctionWorker`; results
  come back through queued signals, so slots here always run on the GUI thread.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThreadPool, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
)

from wawekit.core import constants
from wawekit.core.config import AppConfig, save_config
from wawekit.core.logging_config import setup_logging
from wawekit.gui.dialogs.batch_dialog import BatchDialog
from wawekit.gui.dialogs.chemical_space_dialog import ChemicalSpaceDialog
from wawekit.gui.dialogs.clustering_dialog import ClusteringDialog
from wawekit.gui.dialogs.conformer_dialog import ConformerDialog
from wawekit.gui.dialogs.converter_dialog import ConverterDialog
from wawekit.gui.dialogs.fingerprint_dialog import FingerprintDialog
from wawekit.gui.dialogs.manual_dialog import ManualDialog
from wawekit.gui.dialogs.report_dialog import ReportDialog
from wawekit.gui.dialogs.reproducibility_dialog import ReproducibilityDialog
from wawekit.gui.dialogs.settings_dialog import SettingsDialog
from wawekit.gui.dialogs.similarity_dialog import SimilarityDialog
from wawekit.gui.dialogs.standardize_dialog import StandardizeDialog
from wawekit.gui.dialogs.substructure_dialog import SubstructureDialog
from wawekit.gui.icons import get_icon
from wawekit.gui.themes.theme_manager import ThemeManager
from wawekit.gui.widgets.chemical_space_panel import ChemicalSpacePanel
from wawekit.gui.widgets.conformer_panel import ConformerPanel
from wawekit.gui.widgets.molecule_filter import ScaffoldFilter
from wawekit.gui.widgets.molecule_table import MoleculeTablePanel
from wawekit.gui.widgets.property_filter_panel import PropertyFilterPanel
from wawekit.gui.widgets.reproducibility_panel import ReproducibilityPanel
from wawekit.gui.widgets.scaffold_panel import ScaffoldPanel
from wawekit.gui.widgets.structure_viewer import StructureViewerPanel
from wawekit.gui.widgets.viewer_3d_panel import Viewer3DPanel
from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.models.scaffold import ScaffoldRepresentation
from wawekit.plugins.base import PluginContext
from wawekit.plugins.manager import load_plugins
from wawekit.services.batch import BatchResult, run_batch
from wawekit.services.chemistry.alerts import AlertReport, compute_alerts_for_records
from wawekit.services.chemistry.chemical_space import (
    ProjectionResult,
    project,
)
from wawekit.services.chemistry.clustering import (
    ClusterReport,
    cluster_molecules,
)
from wawekit.services.chemistry.conformers import (
    ConformerReport,
    generate_conformers,
)
from wawekit.services.chemistry.descriptors import (
    DescriptorReport,
    compute_descriptors,
)
from wawekit.services.chemistry.fingerprints import (
    FingerprintReport,
    compute_fingerprints,
)
from wawekit.services.chemistry.scaffolds import (
    ScaffoldGroup,
    ScaffoldReport,
    compute_scaffolds,
    group_scaffolds,
)
from wawekit.services.chemistry.similarity import (
    SimilarityReport,
    search_similar,
)
from wawekit.services.chemistry.standardizer import (
    StandardizationReport,
    standardize_records,
)
from wawekit.services.chemistry.substructure import (
    SubstructureReport,
    search_substructure,
)
from wawekit.services.io.molecule_loader import (
    SUPPORTED_EXTENSIONS,
    LoadReport,
    file_dialog_filter,
)
from wawekit.services.io.molecule_loader import load_file as load_molecule_file
from wawekit.services.reporting import ReportResult, generate_report
from wawekit.services.reproducibility import (
    DivergenceRun,
    analyze_divergence,
    compute_metrics,
)
from wawekit.services.workers import FunctionWorker

logger = logging.getLogger(__name__)

#: Cap on how many individual record errors we list in the summary dialog.
_MAX_ERRORS_SHOWN = 200


class MainWindow(QMainWindow):
    """Top-level window hosting menus, toolbar, docks and the molecule table.

    Parameters
    ----------
    config:
        The loaded application configuration (sizes, theme, ...).
    theme_manager:
        Shared manager used by the View menu to switch themes at runtime.

    """

    def __init__(self, config: AppConfig, theme_manager: ThemeManager) -> None:
        super().__init__()
        self._config = config
        self._theme_manager = theme_manager

        # Load queue state: paths waiting to be parsed, and the active worker
        # (referenced so Python's GC cannot collect it mid-run).
        self._pending_paths: list[Path] = []
        self._active_worker: FunctionWorker | None = None
        # Standardization worker (kept alive for the same GC reason). Loads are
        # paused while it runs so the dataset cannot change mid-pipeline.
        self._std_worker: FunctionWorker | None = None
        # Descriptor worker (same lifetime discipline; loads pause while it runs).
        self._desc_worker: FunctionWorker | None = None
        # Fingerprint worker (ditto).
        self._fp_worker: FunctionWorker | None = None
        # Similarity-search worker (ditto).
        self._sim_worker: FunctionWorker | None = None
        # Scaffold-analysis worker (ditto).
        self._scaffold_worker: FunctionWorker | None = None
        # Conformer-generation worker (ditto).
        self._conf_worker: FunctionWorker | None = None
        # Chemical-space projection worker (ditto).
        self._space_worker: FunctionWorker | None = None
        # Clustering worker (ditto).
        self._cluster_worker: FunctionWorker | None = None
        # Substructure-search worker (ditto), and whether that run filters.
        self._substruct_worker: FunctionWorker | None = None
        self._substruct_only_matches = True
        # Batch pipeline worker and its cancellation event (the first cancellable
        # operation — a batch can run long enough to want stopping).
        self._batch_worker: FunctionWorker | None = None
        self._batch_cancel: threading.Event | None = None
        # Report-generation worker (ditto).
        self._report_worker: FunctionWorker | None = None
        # Reproducibility-audit worker (ditto). Research feature (see
        # services/reproducibility) — not part of the core 20-module roadmap.
        self._repro_worker: FunctionWorker | None = None
        # Background structural-alerts worker. Deliberately NOT part of the
        # busy-guard set: it runs automatically and unobtrusively after a
        # load/standardize/batch, and other actions should stay available
        # while it finishes (see _start_background_alerts).
        self._alerts_worker: FunctionWorker | None = None
        # Encoding used by the last search, so the dialog reopens on it rather
        # than on the defaults — re-encoding a dataset behind the user's back is
        # exactly the silent mixing Module 6 was about.
        self._last_fingerprint: FingerprintOptions | None = None
        # The (non-modal) user manual, created lazily on first Help → Manual.
        self._manual_dialog: ManualDialog | None = None

        self.setWindowTitle(f"{constants.APP_NAME} {constants.APP_VERSION}")
        self.resize(config.window_width, config.window_height)
        self.setAcceptDrops(True)

        self._build_central_widget()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._restore_window_state()
        self._load_plugins()

        logger.info("Main window constructed")

    # ------------------------------------------------------------------ build
    def _build_central_widget(self) -> None:
        """Create a stacked central area: welcome page ↔ molecule table."""
        self._welcome = QLabel(
            f"Welcome to {constants.APP_NAME}\n\n"
            "Open molecule files (SDF, MOL, SMILES) via File → Open\n"
            "or drag and drop them anywhere on this window.",
            alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._welcome.setObjectName("welcomeLabel")

        self._table_panel = MoleculeTablePanel(dark=self._theme_manager.is_dark, parent=self)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._welcome)
        self._stack.addWidget(self._table_panel)
        self.setCentralWidget(self._stack)

    def _build_docks(self) -> None:
        """Create the Workspace dock (loaded files) and the Structure dock."""
        dock = QDockWidget("Workspace", self)
        dock.setObjectName("workspaceDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._sources_list = QListWidget(dock)
        dock.setWidget(self._sources_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
        self._workspace_dock = dock

        structure_dock = QDockWidget("Structure", self)
        structure_dock.setObjectName("structureDock")
        structure_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._structure_panel = StructureViewerPanel(
            dark=self._theme_manager.is_dark, parent=structure_dock
        )
        structure_dock.setWidget(self._structure_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, structure_dock)
        self._structure_dock = structure_dock

        # Scaffolds dock: the grouping view. Tabbed with Workspace on the left so
        # the two navigation panels share space and the table keeps the centre.
        scaffold_dock = QDockWidget("Scaffolds", self)
        scaffold_dock.setObjectName("scaffoldDock")
        scaffold_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._scaffold_panel = ScaffoldPanel(dark=self._theme_manager.is_dark, parent=scaffold_dock)
        scaffold_dock.setWidget(self._scaffold_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, scaffold_dock)
        self.tabifyDockWidget(self._workspace_dock, scaffold_dock)
        self._workspace_dock.raise_()  # Workspace is the default-visible tab
        self._scaffold_dock = scaffold_dock

        # Property Filters dock: range inputs. Tabbed with Workspace on the left.
        filters_dock = QDockWidget("Property Filters", self)
        filters_dock.setObjectName("propertyFilterDock")
        filters_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._property_filter_panel = PropertyFilterPanel(parent=filters_dock)
        filters_dock.setWidget(self._property_filter_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, filters_dock)
        self.tabifyDockWidget(self._workspace_dock, filters_dock)
        self._filters_dock = filters_dock

        # Conformers dock: the 3D viewer + energy table. Tabbed with Structure on
        # the right, since both follow the current molecule selection.
        conformer_dock = QDockWidget("Conformers", self)
        conformer_dock.setObjectName("conformerDock")
        conformer_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._conformer_panel = ConformerPanel(
            dark=self._theme_manager.is_dark, parent=conformer_dock
        )
        conformer_dock.setWidget(self._conformer_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, conformer_dock)
        self.tabifyDockWidget(self._structure_dock, conformer_dock)
        self._conformer_dock = conformer_dock

        # 3D Viewer dock: standalone interactive 3D view with on-the-fly embedding.
        # Tabbed with Structure and Conformers on the right.
        viewer_3d_dock = QDockWidget("3D Viewer", self)
        viewer_3d_dock.setObjectName("viewer3dDock")
        viewer_3d_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self._viewer_3d_panel = Viewer3DPanel(
            dark=self._theme_manager.is_dark, parent=viewer_3d_dock
        )
        viewer_3d_dock.setWidget(self._viewer_3d_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, viewer_3d_dock)
        self.tabifyDockWidget(self._structure_dock, viewer_3d_dock)
        self._structure_dock.raise_()  # Structure is the default-visible right tab
        self._viewer_3d_dock = viewer_3d_dock

        # Chemical Space dock: a wide 2D scatter, so it lives along the bottom
        # spanning the window rather than in a narrow side column.
        space_dock = QDockWidget("Chemical Space", self)
        space_dock.setObjectName("chemicalSpaceDock")
        self._space_panel = ChemicalSpacePanel(dark=self._theme_manager.is_dark, parent=space_dock)
        space_dock.setWidget(self._space_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, space_dock)
        space_dock.hide()  # revealed when a projection is first run
        self._space_dock = space_dock

        # Reproducibility dock: the research feature. Tabbed with Chemical Space
        # along the bottom — both are wide analytical panels, not per-molecule views.
        repro_dock = QDockWidget("Reproducibility", self)
        repro_dock.setObjectName("reproducibilityDock")
        self._repro_panel = ReproducibilityPanel(
            dark=self._theme_manager.is_dark, parent=repro_dock
        )
        repro_dock.setWidget(self._repro_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, repro_dock)
        self.tabifyDockWidget(space_dock, repro_dock)
        repro_dock.hide()  # revealed when an audit is first run
        self._repro_dock = repro_dock

        # Cross-panel wiring: table selection drives the structure viewer,
        # conformer panel and 3D viewer; theme changes re-render every depiction.
        self._table_panel.selection_changed.connect(self._structure_panel.set_record)
        self._table_panel.selection_changed.connect(self._conformer_panel.set_record)
        self._table_panel.selection_changed.connect(self._viewer_3d_panel.set_record)
        self._table_panel.selection_changed.connect(self._on_selection_for_space)
        self._table_panel.similarity_requested.connect(self._on_similarity_requested)
        self._scaffold_panel.scaffold_selected.connect(self._on_scaffold_selected)
        self._scaffold_panel.representation_changed.connect(
            self._on_scaffold_representation_changed
        )
        # Plot → table: a click or lasso in the space selects those molecules.
        self._space_panel.points_selected.connect(self._table_panel.select_records)
        self._property_filter_panel.filters_changed.connect(
            self._table_panel.apply_property_range_filter
        )
        self._theme_manager.theme_changed.connect(self._on_theme_changed)

    def _build_actions(self) -> None:
        """Create reusable QActions shared by menus and the toolbar."""
        self.action_open = QAction(get_icon("open"), "&Open Molecules…", self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        self.action_open.setStatusTip("Open molecule files (SDF, MOL, SMILES)")
        self.action_open.triggered.connect(self._on_open_files)

        self.action_report = QAction(get_icon("report"), "Generate &Report…", self)
        self.action_report.setShortcut("Ctrl+R")
        self.action_report.setStatusTip("Generate a shareable HTML/PDF report of the dataset")
        self.action_report.triggered.connect(self._on_report)

        self.action_settings = QAction(get_icon("settings"), "&Settings…", self)
        self.action_settings.setShortcut(QKeySequence.StandardKey.Preferences)
        self.action_settings.setStatusTip("Edit application settings (theme, logging, layout)")
        self.action_settings.triggered.connect(self._on_settings)

        self.action_standardize = QAction(get_icon("standardize"), "&Standardize…", self)
        self.action_standardize.setShortcut("Ctrl+Shift+S")
        self.action_standardize.setStatusTip(
            "Clean structures: strip salts, neutralize, canonicalize, deduplicate"
        )
        self.action_standardize.triggered.connect(self._on_standardize)

        self.action_descriptors = QAction(get_icon("descriptors"), "Compute &Descriptors", self)
        self.action_descriptors.setShortcut("Ctrl+D")
        self.action_descriptors.setStatusTip(
            "Compute MW, LogP, TPSA, HBD/HBA, rotatable bonds, rings and Lipinski violations"
        )
        self.action_descriptors.triggered.connect(self._on_compute_descriptors)

        self.action_fingerprints = QAction(get_icon("fingerprint"), "Compute &Fingerprints…", self)
        self.action_fingerprints.setShortcut("Ctrl+Shift+F")
        self.action_fingerprints.setStatusTip(
            "Encode structures as bit vectors (Morgan/ECFP, MACCS, RDKit) for similarity search"
        )
        self.action_fingerprints.triggered.connect(self._on_compute_fingerprints)

        self.action_similarity = QAction(get_icon("similarity"), "Si&milarity Search…", self)
        self.action_similarity.setShortcut("Ctrl+Shift+M")
        self.action_similarity.setStatusTip(
            "Rank the dataset by similarity to one query molecule (Tanimoto, Dice or Cosine)"
        )
        self.action_similarity.triggered.connect(self._on_similarity_search)

        self.action_scaffolds = QAction(get_icon("scaffold"), "&Analyze Scaffolds", self)
        self.action_scaffolds.setShortcut("Ctrl+Shift+A")
        self.action_scaffolds.setStatusTip(
            "Group the dataset by Bemis–Murcko scaffold and show scaffold diversity"
        )
        self.action_scaffolds.triggered.connect(self._on_analyze_scaffolds)

        self.action_conformers = QAction(get_icon("conformer"), "Generate &Conformers…", self)
        self.action_conformers.setShortcut("Ctrl+Shift+C")
        self.action_conformers.setStatusTip(
            "Generate and rank 3D conformers (ETKDG + MMFF/UFF) for the selection or dataset"
        )
        self.action_conformers.triggered.connect(self._on_generate_conformers)

        self.action_chemical_space = QAction(get_icon("chemspace"), "Chemical &Space…", self)
        self.action_chemical_space.setShortcut("Ctrl+Shift+P")
        self.action_chemical_space.setStatusTip(
            "Project the dataset into an interactive 2D map (PCA or t-SNE on fingerprints)"
        )
        self.action_chemical_space.triggered.connect(self._on_chemical_space)

        self.action_reproducibility = QAction(get_icon("scaffold"), "&Reproducibility Audit…", self)
        self.action_reproducibility.setShortcut("Ctrl+Shift+R")
        self.action_reproducibility.setStatusTip(
            "Research: compare standardization protocols and attribute divergence causes"
        )
        self.action_reproducibility.triggered.connect(self._on_reproducibility_audit)

        self.action_cluster = QAction(get_icon("cluster"), "&Cluster Molecules…", self)
        self.action_cluster.setShortcut("Ctrl+Shift+K")
        self.action_cluster.setStatusTip(
            "Group similar molecules (Butina or K-Means) into a sortable, colourable cluster id"
        )
        self.action_cluster.triggered.connect(self._on_cluster)

        self.action_substructure = QAction(get_icon("substructure"), "S&ubstructure Search…", self)
        self.action_substructure.setShortcut("Ctrl+Shift+U")
        self.action_substructure.setStatusTip(
            "Find molecules containing a SMARTS/SMILES fragment; highlight the matched atoms"
        )
        self.action_substructure.triggered.connect(self._on_substructure)

        self.action_batch = QAction(get_icon("batch"), "&Batch Processing…", self)
        self.action_batch.setShortcut("Ctrl+B")
        self.action_batch.setStatusTip(
            "Run a pipeline (standardize → descriptors → … → export) over the whole dataset"
        )
        self.action_batch.triggered.connect(self._on_batch)

        self.action_convert = QAction(get_icon("open"), "Con&vert Format…", self)
        self.action_convert.setShortcut("Ctrl+Shift+V")
        self.action_convert.setStatusTip(
            "Convert between molecule file formats (CSV, SDF, MOL, SMILES)"
        )
        self.action_convert.triggered.connect(self._on_convert)

        self.action_quit = QAction("E&xit", self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_quit.setStatusTip("Exit the application")
        self.action_quit.triggered.connect(self.close)

        self.action_toggle_theme = QAction(get_icon("theme"), "&Next Theme", self)
        self.action_toggle_theme.setShortcut("Ctrl+T")
        self.action_toggle_theme.setStatusTip("Cycle to the next look-and-feel theme")
        self.action_toggle_theme.triggered.connect(self._on_toggle_theme)

        # Build checkable actions for the Look & Feel submenu.
        self._look_feel_group = QActionGroup(self)
        self._look_feel_group.setExclusive(True)
        self._look_feel_actions: dict[str, QAction] = {}
        for key in self._theme_manager.available():
            display = self._theme_manager.display_name(key)
            action = QAction(display, self)
            action.setCheckable(True)
            action.setData(key)
            if key == self._theme_manager.current:
                action.setChecked(True)
            action.triggered.connect(self._on_look_feel_selected)
            self._look_feel_group.addAction(action)
            self._look_feel_actions[key] = action

        # QDockWidget provides ready-made checkable show/hide actions — no
        # custom handlers needed, and the checkmark stays in sync for free.
        self.action_toggle_workspace = self._workspace_dock.toggleViewAction()
        self.action_toggle_workspace.setText("&Workspace Panel")
        self.action_toggle_structure = self._structure_dock.toggleViewAction()
        self.action_toggle_structure.setText("&Structure Panel")
        self.action_toggle_scaffolds = self._scaffold_dock.toggleViewAction()
        self.action_toggle_scaffolds.setText("Scaffolds &Panel")
        self.action_toggle_conformers = self._conformer_dock.toggleViewAction()
        self.action_toggle_conformers.setText("&Conformers Panel")
        self.action_toggle_3d = self._viewer_3d_dock.toggleViewAction()
        self.action_toggle_3d.setText("3D &Viewer Panel")
        self.action_toggle_space = self._space_dock.toggleViewAction()
        self.action_toggle_space.setText("Chemical S&pace Panel")
        self.action_toggle_repro = self._repro_dock.toggleViewAction()
        self.action_toggle_repro.setText("Re&producibility Panel")
        self.action_toggle_filters = self._filters_dock.toggleViewAction()
        self.action_toggle_filters.setText("Property &Filters Panel")

        self.action_manual = QAction("&User Manual", self)
        self.action_manual.setShortcut(QKeySequence.StandardKey.HelpContents)  # F1
        self.action_manual.setStatusTip("Open the illustrated user manual")
        self.action_manual.triggered.connect(self._on_manual)

        self.action_about = QAction("&About", self)
        self.action_about.setStatusTip("About this application")
        self.action_about.triggered.connect(self._on_about)

    def _build_menus(self) -> None:
        """Assemble the menu bar from the shared actions."""
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        file_menu.addAction(self.action_open)
        file_menu.addAction(self.action_convert)
        file_menu.addAction(self.action_report)
        file_menu.addSeparator()
        file_menu.addAction(self.action_settings)
        file_menu.addSeparator()
        file_menu.addAction(self.action_quit)

        chemistry_menu = menubar.addMenu("&Chemistry")
        chemistry_menu.addAction(self.action_standardize)
        chemistry_menu.addAction(self.action_descriptors)
        chemistry_menu.addAction(self.action_fingerprints)
        chemistry_menu.addAction(self.action_similarity)
        chemistry_menu.addAction(self.action_scaffolds)
        chemistry_menu.addAction(self.action_conformers)
        chemistry_menu.addAction(self.action_chemical_space)
        chemistry_menu.addAction(self.action_cluster)
        chemistry_menu.addAction(self.action_substructure)
        chemistry_menu.addSeparator()
        chemistry_menu.addAction(self.action_batch)

        research_menu = menubar.addMenu("&Research")
        research_menu.addAction(self.action_reproducibility)

        # Plugins menu: created empty here, populated by _load_plugins() once
        # third-party plugins are discovered — a plugin with nothing to add
        # still gets an (empty, harmless) menu rather than none at all.
        self._plugins_menu = menubar.addMenu("Plu&gins")

        view_menu = menubar.addMenu("&View")
        view_menu.addAction(self.action_toggle_theme)
        view_menu.addSeparator()
        view_menu.addAction(self.action_toggle_workspace)
        view_menu.addAction(self.action_toggle_structure)
        view_menu.addAction(self.action_toggle_scaffolds)
        view_menu.addAction(self.action_toggle_filters)
        view_menu.addAction(self.action_toggle_conformers)
        view_menu.addAction(self.action_toggle_3d)
        view_menu.addAction(self.action_toggle_space)
        view_menu.addAction(self.action_toggle_repro)

        help_menu = menubar.addMenu("&Help")
        help_menu.addAction(self.action_manual)
        help_menu.addSeparator()
        # Look & Feel submenu under Help, matching DataWarrior layout.
        look_feel_menu = QMenu("Look \u0026 Feel", self)
        for action in self._look_feel_group.actions():
            look_feel_menu.addAction(action)
        help_menu.addMenu(look_feel_menu)
        help_menu.addSeparator()
        help_menu.addAction(self.action_about)

    def _build_toolbar(self) -> None:
        """Create the main toolbar. Text-only for now; icons arrive with assets."""
        toolbar = self.addToolBar("Main")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(True)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addAction(self.action_open)
        toolbar.addAction(self.action_standardize)
        toolbar.addAction(self.action_descriptors)
        toolbar.addAction(self.action_fingerprints)
        toolbar.addAction(self.action_similarity)
        toolbar.addAction(self.action_scaffolds)
        toolbar.addAction(self.action_conformers)
        toolbar.addAction(self.action_chemical_space)
        toolbar.addAction(self.action_cluster)
        toolbar.addAction(self.action_substructure)
        toolbar.addSeparator()
        toolbar.addAction(self.action_batch)
        toolbar.addAction(self.action_report)
        toolbar.addSeparator()
        toolbar.addAction(self.action_toggle_theme)

    def _build_statusbar(self) -> None:
        """Create the status bar with a (hidden) progress bar and cancel button."""
        self._progress = QProgressBar(self)
        self._progress.setMaximumWidth(220)
        self._progress.setVisible(False)
        # Only the batch pipeline is cancellable, so the button lives here and is
        # revealed only while a batch runs.
        self._cancel_button = QPushButton("Cancel", self)
        self._cancel_button.setVisible(False)
        self._cancel_button.clicked.connect(self._on_cancel_batch)
        self.statusBar().addPermanentWidget(self._progress)
        self.statusBar().addPermanentWidget(self._cancel_button)
        self.statusBar().showMessage("Ready")

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 — Qt override
        """Accept the drag if it carries at least one supported local file."""
        if any(self._url_is_supported(url) for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 — Qt override
        """Queue every dropped supported file for loading."""
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        event.acceptProposedAction()
        self._enqueue_paths(paths)

    @staticmethod
    def _url_is_supported(url) -> bool:  # noqa: ANN001 — QUrl
        """Return True if ``url`` is a local file with a supported extension."""
        return url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_EXTENSIONS

    # ------------------------------------------------------------ load queue
    def _enqueue_paths(self, paths: list[Path]) -> None:
        """Filter ``paths`` to supported formats, queue them, start loading."""
        supported = [p for p in paths if p.suffix.lower() in SUPPORTED_EXTENSIONS]
        rejected = [p for p in paths if p.suffix.lower() not in SUPPORTED_EXTENSIONS]
        if rejected:
            names = ", ".join(p.name for p in rejected)
            self.statusBar().showMessage(f"Skipped unsupported file(s): {names}", 5000)
            logger.warning("Skipped unsupported file(s): %s", names)
        if supported:
            self._pending_paths.extend(supported)
            self._start_next_load()

    def _start_next_load(self) -> None:
        """Start loading the next queued file, if idle and any remain.

        Loads also wait while standardization or descriptor computation runs —
        those work on a snapshot of the dataset, and appending mid-run would
        leave the new records out of the result.
        """
        if (
            self._active_worker is not None
            or self._std_worker is not None
            or self._desc_worker is not None
            or self._fp_worker is not None
            or self._sim_worker is not None
            or self._scaffold_worker is not None
            or self._conf_worker is not None
            or self._space_worker is not None
            or self._cluster_worker is not None
            or self._substruct_worker is not None
            or self._batch_worker is not None
            or self._report_worker is not None
            or self._repro_worker is not None
        ):
            return
        if not self._pending_paths:
            return
        path = self._pending_paths.pop(0)

        self.action_open.setEnabled(False)
        self._progress.setRange(0, 0)  # busy indicator until first progress signal
        self._progress.setVisible(True)
        self.statusBar().showMessage(f"Loading {path.name}…")

        worker = FunctionWorker(load_molecule_file, path, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_load_finished)
        worker.signals.error.connect(self._on_load_error)
        self._active_worker = worker  # keep alive while the pool runs it
        QThreadPool.globalInstance().start(worker)
        logger.info("Started background load of %s", path)

    def _finish_current_load(self) -> None:
        """Reset per-load UI state and move on to the next queued file."""
        self._active_worker = None
        if not self._pending_paths:
            self._progress.setVisible(False)
            self.action_open.setEnabled(True)
            self._start_background_alerts()  # whole queue drained: audit now
        self._start_next_load()

    # ------------------------------------------------------------ run helpers
    def _set_actions_busy(self, busy: bool) -> None:
        """Enable or disable every action that must not run concurrently.

        Each dataset-wide operation works on a snapshot, so allowing a second
        one to start mid-run would let the two disagree about what the dataset
        is. One helper keeps the set consistent as more operations arrive.
        """
        for action in (
            self.action_open,
            self.action_standardize,
            self.action_descriptors,
            self.action_fingerprints,
            self.action_similarity,
            self.action_scaffolds,
            self.action_conformers,
            self.action_chemical_space,
            self.action_cluster,
            self.action_substructure,
            self.action_batch,
            self.action_report,
            self.action_reproducibility,
        ):
            action.setEnabled(not busy)

    def _begin_run(self, total: int, message: str) -> None:
        """Put the UI into 'long operation running' state."""
        self._set_actions_busy(True)
        self._progress.setRange(0, total)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self.statusBar().showMessage(message)

    # --------------------------------------------------------------- handlers
    def _on_open_files(self) -> None:
        """Show the file dialog and queue the chosen files."""
        filenames, _ = QFileDialog.getOpenFileNames(
            self, "Open Molecule Files", "", file_dialog_filter()
        )
        if filenames:
            self._enqueue_paths([Path(f) for f in filenames])

    def _on_load_progress(self, done: int, total: int) -> None:
        """Update the status-bar progress bar from worker signals."""
        if self._progress.maximum() != total:
            self._progress.setRange(0, total)
        self._progress.setValue(done)

    def _on_load_finished(self, report: LoadReport) -> None:
        """Integrate a finished load: table, dock list, status, error summary."""
        self._table_panel.append_records(report.records)
        if self._table_panel.row_count:
            self._stack.setCurrentWidget(self._table_panel)
            self._property_filter_panel.update_ranges(list(self._table_panel.model.records))

        self._sources_list.addItem(
            f"{report.source.name}  —  {report.n_loaded} molecule(s)"
            + (f", {report.n_failed} error(s)" if report.n_failed else "")
        )
        self.statusBar().showMessage(
            f"Loaded {report.n_loaded} molecule(s) from {report.source.name} "
            f"({report.n_failed} failed) — {self._table_panel.row_count} total",
            8000,
        )
        if report.errors:
            self._show_error_summary(report)
        self._finish_current_load()

    def _on_load_error(self, message: str) -> None:
        """Report a whole-file failure (unreadable/unsupported file)."""
        QMessageBox.warning(self, "Could not load file", message)
        self.statusBar().showMessage("Load failed", 5000)
        self._finish_current_load()

    def _show_error_summary(self, report: LoadReport) -> None:
        """Show a dialog summarizing per-record failures, details on demand."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Loaded with errors")
        box.setText(
            f"{report.n_failed} record(s) in {report.source.name} could not be read.\n"
            f"{report.n_loaded} molecule(s) loaded successfully."
        )
        shown = report.errors[:_MAX_ERRORS_SHOWN]
        details = "\n".join(str(err) for err in shown)
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    def _on_standardize(self) -> None:
        """Configure and launch the standardization pipeline on the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before standardizing", 4000)
            return
        options = StandardizeDialog.get_options(self)
        if options is None:
            return  # cancelled

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Standardizing {len(records)} molecule(s)…")

        worker = FunctionWorker(standardize_records, records, options, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_standardize_finished)
        worker.signals.error.connect(self._on_standardize_error)
        self._std_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started standardization of %d record(s)", len(records))

    def _reset_derived_views(self) -> None:
        """Clear every panel/filter that pointed at the previous dataset.

        Used whenever the record objects are *replaced* (standardization, a batch
        run): the old projection, conformers, scaffold grouping and substructure
        filter all reference records that no longer exist.
        """
        self._structure_panel.set_record(None)
        self._conformer_panel.set_record(None)
        self._viewer_3d_panel.set_record(None)
        self._property_filter_panel.clear()
        self._space_panel.clear()
        self._repro_panel.clear()  # the audit referenced the old record objects
        self._table_panel.apply_substructure_filter(False)
        self._reset_scaffold_view()
        # New record objects always start with alerts uncomputed; audit them.
        self._start_background_alerts()

    def _on_standardize_finished(self, report: StandardizationReport) -> None:
        """Adopt the standardized dataset and present the change report."""
        self._table_panel.set_records(report.records)
        self._reset_derived_views()
        self._sources_list.addItem(
            f"Standardized  —  {report.n_changed} changed, "
            f"{report.duplicates_removed} duplicate(s) removed"
        )
        self.statusBar().showMessage(
            f"Standardized: {report.n_records} molecule(s), {report.n_changed} changed, "
            f"{report.duplicates_removed} duplicate(s) removed, "
            f"{len(report.failures)} failure(s)",
            10000,
        )
        self._show_standardize_summary(report)
        self._finish_standardize()

    def _on_standardize_error(self, message: str) -> None:
        """Report a whole-pipeline failure (should be rare; per-record errors are handled)."""
        QMessageBox.warning(self, "Standardization failed", message)
        self._finish_standardize()

    def _finish_standardize(self) -> None:
        """Reset UI state after standardization and resume any queued loads."""
        self._std_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    # ------------------------------------------------------------------ alerts
    def _start_background_alerts(self) -> None:
        """Automatically audit the current dataset for structural alerts.

        Checking a molecule against several hundred PAINS/Brenk/NIH SMARTS
        patterns is too slow to run synchronously during a table repaint
        (which is how this used to be triggered — see
        ``services/chemistry/alerts.py`` for the full story), but light
        enough overall that it should not block every other action the way
        standardize/descriptors/etc. do. So this runs on a background worker
        deliberately outside :meth:`_set_actions_busy`'s guard, and is a
        silent, automatic pass — no progress bar, no dialog — matching the
        "WaweKit automatically audits loaded structures" promise in the
        manual (Help → User Manual).
        """
        if self._alerts_worker is not None or self._table_panel.row_count == 0:
            return  # already running; the next trigger will catch what's left
        records = list(self._table_panel.model.records)
        worker = FunctionWorker(compute_alerts_for_records, records)
        worker.signals.finished.connect(self._on_alerts_finished)
        worker.signals.error.connect(self._on_alerts_error)
        self._alerts_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started background structural-alerts audit for %d record(s)", len(records))

    def _on_alerts_finished(self, report: AlertReport) -> None:
        """Repaint the Alerts column now that the cache is filled in."""
        self._alerts_worker = None
        self._table_panel.refresh_alerts()
        logger.info(
            "Alerts audit complete: %d checked (%d with warnings), %d reused",
            report.computed,
            report.with_alerts,
            report.reused,
        )
        # Re-trigger ONLY if the dataset changed while this pass was running
        # (records appended, or the whole set replaced) — checked by count and
        # by scanning for any still-uncomputed record. Without this condition,
        # every pass would immediately reschedule itself forever; with it, the
        # chain runs at most once more per actual change and then stops.
        current = self._table_panel.model.records
        if len(current) != len(report.records) or any(not r.alerts_computed for r in current):
            self._start_background_alerts()

    def _on_alerts_error(self, message: str) -> None:
        """Log a failed audit — silent to the user, since the trigger itself was."""
        self._alerts_worker = None
        logger.warning("Background structural-alerts audit failed: %s", message)

    def _show_standardize_summary(self, report: StandardizationReport) -> None:
        """Show counts up front, full per-molecule provenance behind Details."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Standardization complete")
        box.setText(
            f"{report.n_records} molecule(s) in the dataset.\n"
            f"{report.n_changed} modified · {report.duplicates_removed} duplicate(s) removed · "
            f"{len(report.failures)} failure(s)."
        )
        details: list[str] = [str(change) for change in report.changed[:_MAX_ERRORS_SHOWN]]
        if report.failures:
            details.append("")
            details.append("Failures:")
            details.extend(report.failures[:_MAX_ERRORS_SHOWN])
        if details:
            box.setDetailedText("\n".join(details))
        box.exec()

    # ------------------------------------------------------------ descriptors
    def _on_compute_descriptors(self) -> None:
        """Launch descriptor computation over the loaded dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before computing descriptors", 4000)
            return

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Computing descriptors for {len(records)} molecule(s)…")

        worker = FunctionWorker(compute_descriptors, records, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_descriptors_finished)
        worker.signals.error.connect(self._on_descriptors_error)
        self._desc_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started descriptor computation for %d record(s)", len(records))

    def _on_descriptors_finished(self, report: DescriptorReport) -> None:
        """Repaint the descriptor columns and report the run."""
        # Values were cached on the same record objects the table already holds,
        # so we refresh the affected columns rather than swapping the dataset.
        self._table_panel.refresh_descriptors()
        self._property_filter_panel.update_ranges(list(self._table_panel.model.records))
        self.statusBar().showMessage(
            f"Descriptors: {report.computed} computed, {report.reused} reused, "
            f"{report.n_failed} failure(s)",
            8000,
        )
        if report.failures:
            self._show_descriptor_failures(report)
        self._finish_descriptors()

    def _on_descriptors_error(self, message: str) -> None:
        """Report a whole-run failure (per-molecule failures are handled inline)."""
        QMessageBox.warning(self, "Descriptor computation failed", message)
        self._finish_descriptors()

    def _finish_descriptors(self) -> None:
        """Reset UI state after descriptors and resume any queued loads."""
        self._desc_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_descriptor_failures(self, report: DescriptorReport) -> None:
        """List molecules whose descriptors could not be computed."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Descriptors computed with errors")
        box.setText(
            f"{report.n_failed} molecule(s) could not be processed.\n"
            f"{report.computed} computed successfully."
        )
        shown = report.failures[:_MAX_ERRORS_SHOWN]
        details = "\n".join(shown)
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # ----------------------------------------------------------- fingerprints
    def _on_compute_fingerprints(self) -> None:
        """Configure and launch fingerprint computation over the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before computing fingerprints", 4000)
            return
        options = FingerprintDialog.get_options(self)
        if options is None:
            return  # cancelled

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(
            len(records),
            f"Computing {options.label} fingerprints for {len(records)} molecule(s)…",
        )

        worker = FunctionWorker(compute_fingerprints, records, options, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_fingerprints_finished)
        worker.signals.error.connect(self._on_fingerprints_error)
        self._fp_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started %s fingerprints for %d record(s)", options.label, len(records))

    def _on_fingerprints_finished(self, report: FingerprintReport) -> None:
        """Repaint the fingerprint column and report the run."""
        # Cached on the same record objects the table holds → repaint, no swap.
        self._table_panel.refresh_fingerprints()
        self.statusBar().showMessage(
            f"Fingerprints ({report.options.label}): {report.computed} computed, "
            f"{report.reused} reused, {report.n_failed} failure(s)",
            8000,
        )
        if report.failures:
            self._show_fingerprint_failures(report)
        self._finish_fingerprints()

    def _on_fingerprints_error(self, message: str) -> None:
        """Report a whole-run failure (per-molecule failures are handled inline)."""
        QMessageBox.warning(self, "Fingerprint computation failed", message)
        self._finish_fingerprints()

    def _finish_fingerprints(self) -> None:
        """Reset UI state after fingerprints and resume any queued loads."""
        self._fp_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_fingerprint_failures(self, report: FingerprintReport) -> None:
        """List molecules whose fingerprint could not be computed."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Fingerprints computed with errors")
        box.setText(
            f"{report.n_failed} molecule(s) could not be processed.\n"
            f"{report.computed} computed successfully."
        )
        details = "\n".join(report.failures[:_MAX_ERRORS_SHOWN])
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # ------------------------------------------------------------- similarity
    def _on_similarity_requested(self, record: MoleculeRecord) -> None:
        """Run a search from the table's right-click menu, pre-filled with ``record``."""
        self._start_similarity_search(query=record)

    def _on_similarity_search(self) -> None:
        """Run a search from the menu/toolbar, pre-filled with the selection if any."""
        selected = self._table_panel.selected_records()
        self._start_similarity_search(query=selected[0] if len(selected) == 1 else None)

    def _start_similarity_search(self, query: MoleculeRecord | None) -> None:
        """Configure and launch a similarity search over the dataset.

        Both entry points land here: the only difference between them is which
        molecule the dialog opens on, and the dialog handles ``None`` by asking
        the user to paste one.
        """
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before searching", 4000)
            return
        request = SimilarityDialog.get_request(query, self._last_fingerprint, self)
        if request is None:
            return  # cancelled, or no usable query

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._last_fingerprint = request.fingerprint
        self._begin_run(
            len(records),
            f"Searching {len(records)} molecule(s) for similarity to {request.query_name}…",
        )

        worker = FunctionWorker(search_similar, records, request, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_similarity_finished)
        worker.signals.error.connect(self._on_similarity_error)
        self._sim_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started similarity search: %s", request.query_name)

    def _on_similarity_finished(self, report: SimilarityReport) -> None:
        """Rank the table by the new scores and report the run."""
        # Scores were cached on the same record objects the table holds, so this
        # repaints and re-sorts rather than swapping the dataset.
        self._table_panel.refresh_similarity()
        self._sources_list.addItem(
            f"Similarity  —  {report.query.metric} vs {report.query.name}, "
            f"{report.n_scored} scored"
        )
        best = report.ranked[0] if report.ranked else None
        self.statusBar().showMessage(
            f"{report.query.label}: {report.n_scored} scored"
            + (f", best {best.name} at {best.similarity.display}" if best else "")
            + (f", {report.n_skipped} skipped" if report.n_skipped else "")
            + " — sorted by score; filter with e.g. 'Sim >= 0.7'",
            12000,
        )
        if report.skipped:
            self._show_similarity_skipped(report)
        self._finish_similarity()

    def _on_similarity_error(self, message: str) -> None:
        """Report a whole-run failure (per-molecule problems are handled inline)."""
        QMessageBox.warning(self, "Similarity search failed", message)
        self._finish_similarity()

    def _finish_similarity(self) -> None:
        """Reset UI state after a search and resume any queued loads."""
        self._sim_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_similarity_skipped(self, report: SimilarityReport) -> None:
        """List molecules that could not be scored, and why."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Search completed with skipped molecules")
        box.setText(
            f"{report.n_skipped} molecule(s) could not be scored and are blank in the "
            f"Similarity column.\n{report.n_scored} scored successfully."
        )
        details = "\n".join(report.skipped[:_MAX_ERRORS_SHOWN])
        if report.n_skipped > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_skipped - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # -------------------------------------------------------------- scaffolds
    def _on_analyze_scaffolds(self) -> None:
        """Launch Bemis–Murcko scaffold analysis over the loaded dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before analyzing scaffolds", 4000)
            return

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Analyzing scaffolds for {len(records)} molecule(s)…")

        worker = FunctionWorker(compute_scaffolds, records, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_scaffolds_finished)
        worker.signals.error.connect(self._on_scaffolds_error)
        self._scaffold_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started scaffold analysis for %d record(s)", len(records))

    def _on_scaffolds_finished(self, report: ScaffoldReport) -> None:
        """Repaint the scaffold column, group the dataset, and reveal the panel."""
        # Scaffolds were cached on the same record objects the table holds, so
        # this repaints the column rather than swapping the dataset.
        self._table_panel.refresh_scaffolds()
        self._regroup_scaffolds()
        self._scaffold_dock.raise_()  # bring the Scaffolds tab to the front
        self.statusBar().showMessage(
            f"Scaffolds: {report.computed} computed, {report.reused} reused, "
            f"{report.n_failed} failure(s) — see the Scaffolds panel",
            9000,
        )
        if report.failures:
            self._show_scaffold_failures(report)
        self._finish_scaffolds()

    def _on_scaffolds_error(self, message: str) -> None:
        """Report a whole-run failure (per-molecule problems are handled inline)."""
        QMessageBox.warning(self, "Scaffold analysis failed", message)
        self._finish_scaffolds()

    def _finish_scaffolds(self) -> None:
        """Reset UI state after scaffold analysis and resume any queued loads."""
        self._scaffold_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _regroup_scaffolds(self) -> None:
        """Rebuild scaffold groups for the panel's current representation."""
        representation = self._scaffold_panel.representation
        records = list(self._table_panel.model.records)
        groups = group_scaffolds(records, representation)
        self._scaffold_panel.set_groups(groups, representation, self._table_panel.row_count)

    def _on_scaffold_representation_changed(self, representation: ScaffoldRepresentation) -> None:
        """Switch exact/generic: repaint the column, regroup, drop the stale filter.

        The scaffold keys differ between representations, so a filter chosen
        under one is meaningless under the other and is cleared rather than
        silently matching nothing.
        """
        self._table_panel.set_scaffold_representation(representation)
        self._table_panel.apply_scaffold_filter(None)
        self._scaffold_panel.clear_selection()
        self._regroup_scaffolds()

    def _on_scaffold_selected(self, group: ScaffoldGroup | None) -> None:
        """Filter the table to one scaffold's members, or clear the restriction."""
        if group is None:
            self._table_panel.apply_scaffold_filter(None)
            self.statusBar().showMessage("Scaffold filter cleared", 3000)
            return
        self._table_panel.apply_scaffold_filter(ScaffoldFilter(group.key, group.representation))
        self.statusBar().showMessage(
            f"Filtered to {group.size} molecule(s) sharing {group.label}", 6000
        )

    def _show_scaffold_failures(self, report: ScaffoldReport) -> None:
        """List molecules whose scaffold could not be computed."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Scaffolds computed with errors")
        box.setText(
            f"{report.n_failed} molecule(s) could not be processed.\n"
            f"{report.computed} computed successfully."
        )
        details = "\n".join(report.failures[:_MAX_ERRORS_SHOWN])
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    def _reset_scaffold_view(self) -> None:
        """Clear scaffold groups and any filter after the dataset is replaced."""
        self._table_panel.apply_scaffold_filter(None)
        self._scaffold_panel.clear_selection()
        self._scaffold_panel.set_groups([], ScaffoldRepresentation.MURCKO, 0)

    # ------------------------------------------------------------- conformers
    def _on_generate_conformers(self) -> None:
        """Configure and launch 3D conformer generation.

        Conformer generation is far heavier than the 2D operations, so it runs
        on the *selection* when there is one, falling back to the whole dataset
        only when nothing is selected.
        """
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before generating conformers", 4000)
            return
        options = ConformerDialog.get_options(self)
        if options is None:
            return  # cancelled

        selected = self._table_panel.selected_records()
        records = selected if selected else list(self._table_panel.model.records)
        scope = "selection" if selected else "dataset"
        self._begin_run(
            len(records),
            f"Generating conformers for {len(records)} molecule(s) ({scope})…",
        )

        worker = FunctionWorker(generate_conformers, records, options, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_conformers_finished)
        worker.signals.error.connect(self._on_conformers_error)
        self._conf_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started conformer generation for %d record(s)", len(records))

    def _on_conformers_finished(self, report: ConformerReport) -> None:
        """Show conformers for the current molecule and report the run."""
        # Conformers were cached on the record objects the table holds. Show them
        # for whatever is selected (or the first record after a dataset run).
        selected = self._table_panel.selected_records()
        records = self._table_panel.model.records
        to_show = selected[0] if selected else (records[0] if records else None)
        if to_show is not None:
            self._conformer_panel.set_record(to_show)
        self._conformer_dock.raise_()
        self.statusBar().showMessage(
            f"Conformers: {report.computed} molecule(s), {report.total_conformers} conformer(s), "
            f"{report.reused} reused, {report.n_failed} failure(s) — see the Conformers panel",
            10000,
        )
        if report.failures:
            self._show_conformer_failures(report)
        self._finish_conformers()

    def _on_conformers_error(self, message: str) -> None:
        """Report a whole-run failure (per-molecule problems are handled inline)."""
        QMessageBox.warning(self, "Conformer generation failed", message)
        self._finish_conformers()

    def _finish_conformers(self) -> None:
        """Reset UI state after conformer generation and resume any queued loads."""
        self._conf_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_conformer_failures(self, report: ConformerReport) -> None:
        """List molecules whose conformers could not be generated."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Conformers generated with errors")
        box.setText(
            f"{report.n_failed} molecule(s) could not be embedded.\n"
            f"{report.computed} generated successfully."
        )
        details = "\n".join(report.failures[:_MAX_ERRORS_SHOWN])
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # -------------------------------------------------------- chemical space
    def _on_chemical_space(self) -> None:
        """Configure and launch a chemical-space projection over the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before projecting", 4000)
            return
        options = ChemicalSpaceDialog.get_options(self)
        if options is None:
            return  # cancelled

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Projecting {len(records)} molecule(s) — {options.label}…")

        worker = FunctionWorker(project, records, options, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_space_finished)
        worker.signals.error.connect(self._on_space_error)
        self._space_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started chemical-space projection: %s", options.label)

    def _on_space_finished(self, result: ProjectionResult) -> None:
        """Show the projection and reveal the Chemical Space dock."""
        self._space_panel.set_projection(result)
        # Reflect the table's current selection in the fresh plot.
        self._space_panel.highlight_records(self._table_panel.selected_records())
        self._space_dock.show()
        self._space_dock.raise_()
        self.statusBar().showMessage(
            f"Chemical space: {result.n_points} molecule(s) projected"
            + (f", {result.n_skipped} skipped" if result.n_skipped else "")
            + " — hover a point, click or lasso to select",
            10000,
        )
        if result.skipped:
            self._show_space_skipped(result)
        self._finish_space()

    def _on_space_error(self, message: str) -> None:
        """Report a whole-run failure (e.g. too few molecules to project)."""
        QMessageBox.warning(self, "Chemical space projection failed", message)
        self._finish_space()

    def _finish_space(self) -> None:
        """Reset UI state after a projection and resume any queued loads."""
        self._space_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_space_skipped(self, result: ProjectionResult) -> None:
        """List molecules left out of the projection (no usable fingerprint)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Projected with skipped molecules")
        box.setText(
            f"{result.n_skipped} molecule(s) could not be projected and are absent "
            f"from the plot.\n{result.n_points} placed successfully."
        )
        details = "\n".join(result.skipped[:_MAX_ERRORS_SHOWN])
        if result.n_skipped > _MAX_ERRORS_SHOWN:
            details += f"\n… and {result.n_skipped - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    def _on_selection_for_space(self, _record: MoleculeRecord | None) -> None:
        """Mirror the table's selection onto the chemical-space plot (table → plot).

        Uses the full multi-row selection, not just the current record, so a
        lasso round-trips correctly. ``highlight_records`` never emits, so this
        cannot loop back into another table selection.
        """
        self._space_panel.highlight_records(self._table_panel.selected_records())

    # -------------------------------------------------------------- clustering
    def _on_cluster(self) -> None:
        """Configure and launch clustering over the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before clustering", 4000)
            return
        options = ClusteringDialog.get_options(self)
        if options is None:
            return  # cancelled

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Clustering {len(records)} molecule(s) — {options.label}…")

        worker = FunctionWorker(cluster_molecules, records, options, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_cluster_finished)
        worker.signals.error.connect(self._on_cluster_error)
        self._cluster_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started clustering: %s", options.label)

    def _on_cluster_finished(self, report: ClusterReport) -> None:
        """Repaint the cluster column and colour the space map by cluster."""
        self._table_panel.refresh_clusters()
        # Paint the chemical-space plot by cluster so the families light up; if
        # no projection is on screen yet, this just presets the colour choice.
        self._space_panel.set_color_by("Cluster")
        self.statusBar().showMessage(
            f"Clustered {report.clustered} molecule(s) into {report.n_clusters} cluster(s) "
            f"(largest {report.largest_cluster_size})"
            + (f", {report.n_skipped} skipped" if report.n_skipped else "")
            + " — sort the Cluster column, or colour the map by Cluster",
            12000,
        )
        if report.skipped:
            self._show_cluster_skipped(report)
        self._finish_cluster()

    def _on_cluster_error(self, message: str) -> None:
        """Report a whole-run failure (e.g. too few molecules to cluster)."""
        QMessageBox.warning(self, "Clustering failed", message)
        self._finish_cluster()

    def _finish_cluster(self) -> None:
        """Reset UI state after clustering and resume any queued loads."""
        self._cluster_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_cluster_skipped(self, report: ClusterReport) -> None:
        """List molecules left out of the clustering (no usable fingerprint)."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Clustered with skipped molecules")
        box.setText(
            f"{report.n_skipped} molecule(s) could not be clustered and are blank "
            f"in the Cluster column.\n{report.clustered} clustered successfully."
        )
        details = "\n".join(report.skipped[:_MAX_ERRORS_SHOWN])
        if report.n_skipped > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_skipped - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # ---------------------------------------------------------- substructure
    def _on_substructure(self) -> None:
        """Configure and launch a substructure search over the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before searching", 4000)
            return
        result = SubstructureDialog.get_query(self)
        if result is None:
            return  # cancelled, or invalid query
        query, only_matches = result
        self._substruct_only_matches = only_matches

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Searching {len(records)} molecule(s) for {query.label}…")

        worker = FunctionWorker(search_substructure, records, query, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_substructure_finished)
        worker.signals.error.connect(self._on_substructure_error)
        self._substruct_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started substructure search: %s", query.label)

    def _on_substructure_finished(self, report: SubstructureReport) -> None:
        """Highlight matches, refresh the column, and optionally filter."""
        # Repaint thumbnails + column (the delegate re-highlights), re-render the
        # selected molecule big, and apply the "matches only" filter if chosen.
        self._table_panel.refresh_substructure()
        self._table_panel.apply_substructure_filter(self._substruct_only_matches)
        self._structure_panel.refresh()
        self.statusBar().showMessage(
            f"Substructure: {report.matched} of {report.n_records} matched {report.query.label}"
            + (" — filtered to matches" if self._substruct_only_matches else "")
            + (f", {report.n_failed} failed" if report.n_failed else ""),
            12000,
        )
        if report.failures:
            self._show_substructure_failures(report)
        self._finish_substructure()

    def _on_substructure_error(self, message: str) -> None:
        """Report a whole-run failure (e.g. an unparseable query)."""
        QMessageBox.warning(self, "Substructure search failed", message)
        self._finish_substructure()

    def _finish_substructure(self) -> None:
        """Reset UI state after a search and resume any queued loads."""
        self._substruct_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _show_substructure_failures(self, report: SubstructureReport) -> None:
        """List molecules that could not be searched."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Search completed with errors")
        box.setText(
            f"{report.n_failed} molecule(s) could not be searched.\n"
            f"{report.matched} matched the query."
        )
        details = "\n".join(report.failures[:_MAX_ERRORS_SHOWN])
        if report.n_failed > _MAX_ERRORS_SHOWN:
            details += f"\n… and {report.n_failed - _MAX_ERRORS_SHOWN} more (see log file)"
        box.setDetailedText(details)
        box.exec()

    # ---------------------------------------------------------------- batch
    def _on_batch(self) -> None:
        """Configure and launch a batch pipeline over the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before running a batch", 4000)
            return
        config = BatchDialog.get_config(self)
        if config is None or not config.has_any_step:
            return

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._batch_cancel = threading.Event()
        self._begin_run(len(records), f"Running batch over {len(records)} molecule(s)…")
        self._cancel_button.setVisible(True)

        worker = FunctionWorker(
            run_batch, records, config, cancel_event=self._batch_cancel, inject_progress=True
        )
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_batch_finished)
        worker.signals.error.connect(self._on_batch_error)
        self._batch_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started batch pipeline")

    def _on_batch_finished(self, result: BatchResult) -> None:
        """Adopt the processed dataset, reset dependent views, and report."""
        # The pipeline may have replaced the records (standardization), so swap
        # the whole dataset and clear everything that pointed at the old one.
        self._table_panel.set_records(result.records)
        self._reset_derived_views()
        self._property_filter_panel.update_ranges(list(self._table_panel.model.records))

        verb = "cancelled" if result.cancelled else "complete"
        export_note = (
            f", exported {result.exported} to {result.export_path.name}"
            if result.export_path is not None
            else ""
        )
        self._sources_list.addItem(f"Batch {verb}  —  {len(result.records)} molecule(s)")
        self.statusBar().showMessage(
            f"Batch {verb}: {len(result.records)} molecule(s){export_note}", 12000
        )
        self._show_batch_summary(result)
        self._finish_batch()

    def _on_batch_error(self, message: str) -> None:
        """Report a whole-pipeline failure (per-molecule errors are handled inside)."""
        QMessageBox.warning(self, "Batch failed", message)
        self._finish_batch()

    def _finish_batch(self) -> None:
        """Reset UI state after a batch and resume any queued loads."""
        self._batch_worker = None
        self._batch_cancel = None
        self._cancel_button.setVisible(False)
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    def _on_cancel_batch(self) -> None:
        """Ask the running batch to stop at the next safe point."""
        if self._batch_cancel is not None:
            self._batch_cancel.set()
            self.statusBar().showMessage("Cancelling batch…")

    def _show_batch_summary(self, result: BatchResult) -> None:
        """Show the per-step summary of a batch run."""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Batch cancelled" if result.cancelled else "Batch complete")
        headline = "The batch was cancelled." if result.cancelled else "The batch finished."
        box.setText(f"{headline}\n{len(result.records)} molecule(s) in the dataset.")
        if result.summaries:
            box.setDetailedText("\n".join(result.summaries))
        box.exec()

    # ---------------------------------------------------------------- reports
    def _on_report(self) -> None:
        """Configure and generate a shareable report of the dataset."""
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before generating a report", 4000)
            return
        config = ReportDialog.get_config(self)
        if config is None:
            return

        records = list(self._table_panel.model.records)  # snapshot for the worker
        self._begin_run(len(records), f"Generating report for {len(records)} molecule(s)…")

        worker = FunctionWorker(generate_report, records, config, inject_progress=True)
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_report_finished)
        worker.signals.error.connect(self._on_report_error)
        self._report_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started report generation: %s", ", ".join(config.formats))

    def _on_report_finished(self, result: ReportResult) -> None:
        """Report the written files and offer to open one."""
        names = ", ".join(p.name for p in result.paths)
        self._sources_list.addItem(f"Report  —  {names}")
        self.statusBar().showMessage(f"Report written: {names}", 10000)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Report generated")
        box.setText(
            f"Wrote {len(result.paths)} file(s) for {result.n_molecules} molecule(s):\n"
            + "\n".join(str(p) for p in result.paths)
        )
        open_button = box.addButton("Open", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_button and result.paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.paths[0].resolve())))
        self._finish_report()

    def _on_report_error(self, message: str) -> None:
        """Report a failure to generate the report."""
        QMessageBox.warning(self, "Report generation failed", message)
        self._finish_report()

    def _finish_report(self) -> None:
        """Reset UI state after a report and resume any queued loads."""
        self._report_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    # ------------------------------------------------------- research: repro audit
    def _on_reproducibility_audit(self) -> None:
        """Configure and launch a standardization-reproducibility audit.

        Research feature: compares standardization protocols across the whole
        dataset and (optionally) attributes each disagreement to a specific
        operation via ablation. See services/reproducibility for the methodology.
        """
        if self._table_panel.row_count == 0:
            self.statusBar().showMessage("Load molecules before running an audit", 4000)
            return
        options = ReproducibilityDialog.get_options(self)
        if options is None:
            return  # cancelled
        protocols, attribute_causes = options

        records = [(r.name, r.mol) for r in self._table_panel.model.records]
        self._begin_run(
            len(records),
            f"Auditing {len(records)} molecule(s) across {len(protocols)} protocol(s)…",
        )

        worker = FunctionWorker(
            analyze_divergence, records, protocols, attribute_causes, inject_progress=True
        )
        worker.signals.progress.connect(self._on_load_progress)
        worker.signals.finished.connect(self._on_reproducibility_finished)
        worker.signals.error.connect(self._on_reproducibility_error)
        self._repro_worker = worker
        QThreadPool.globalInstance().start(worker)
        logger.info("Started reproducibility audit over %d record(s)", len(records))

    def _on_reproducibility_finished(self, run: DivergenceRun) -> None:
        """Compute metrics from the completed run and show the panel."""
        metrics = compute_metrics(run)
        self._repro_panel.set_results(run, metrics)
        self._repro_dock.show()
        self._repro_dock.raise_()
        self.statusBar().showMessage(
            f"Audit complete: {metrics.n_labile}/{metrics.n_molecules} molecule(s) labile "
            f"(SMILES-reproducibility {metrics.smiles_reproducibility:.0%}, "
            f"InChIKey-reproducibility {metrics.inchikey_reproducibility:.0%})",
            12000,
        )
        self._finish_reproducibility()

    def _on_reproducibility_error(self, message: str) -> None:
        """Report a whole-run failure."""
        QMessageBox.warning(self, "Reproducibility audit failed", message)
        self._finish_reproducibility()

    def _finish_reproducibility(self) -> None:
        """Reset UI state after an audit and resume any queued loads."""
        self._repro_worker = None
        self._progress.setVisible(False)
        self._set_actions_busy(False)
        self._start_next_load()

    # ---------------------------------------------------------------- settings
    def _on_settings(self) -> None:
        """Open the Settings dialog and apply + persist any changes."""
        new_config = SettingsDialog.edit(self._config, self)
        if new_config is None:
            return  # cancelled

        if new_config.theme != self._theme_manager.current:
            self._theme_manager.apply(new_config.theme)  # emits theme_changed
        if new_config.log_level != self._config.log_level:
            setup_logging(new_config.log_level)

        self._config = new_config
        try:
            save_config(new_config)
        except OSError:
            logger.exception("Failed to save settings")
            self.statusBar().showMessage("Could not save settings (see log)", 5000)
        else:
            self.statusBar().showMessage("Settings saved", 4000)

    def _restore_window_state(self) -> None:
        """Restore the saved window geometry and dock layout, if enabled.

        Runs after the resize to the config default size, so a saved geometry
        wins and a first run falls back to the default. ``restoreState`` relies
        on every dock and the toolbar having an ``objectName`` (they do).
        """
        if not self._config.remember_window_geometry:
            return
        settings = QSettings()
        geometry = settings.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value("windowState")
        if state is not None:
            self.restoreState(state)

    # --------------------------------------------------------------- plugins
    def _load_plugins(self) -> None:
        """Discover and activate installed plugins (Module 16).

        Plugins are third-party, untrusted code: a plugin that fails to import
        or raises during activation is logged and skipped, never allowed to
        prevent the application from starting — the same resilience discipline
        every chemistry service in this app applies to a bad molecule, applied
        here to a bad plugin.
        """
        context = PluginContext(
            add_menu_action=self._add_plugin_menu_action, add_dock=self._add_plugin_dock
        )
        report = load_plugins(context)
        if report.loaded:
            names = ", ".join(p.name for p in report.loaded)
            logger.info("Loaded %d plugin(s): %s", len(report.loaded), names)
        for failure in report.failures:
            logger.warning("Plugin %r failed to load: %s", failure.entry_point_name, failure.error)

    def _add_plugin_menu_action(self, label: str, callback) -> None:  # noqa: ANN001
        """Add ``label`` to the Plugins menu, calling ``callback`` when triggered.

        The callback signature is deliberately unconstrained (a plugin author
        should not need to import PySide6 to write one) — Qt's ``triggered``
        signal is happy to call any zero-argument callable.
        """
        action = QAction(label, self)
        action.triggered.connect(callback)
        self._plugins_menu.addAction(action)

    def _add_plugin_dock(self, title: str, widget) -> None:  # noqa: ANN001 — QWidget
        """Add ``widget`` as a new dock panel titled ``title``."""
        dock = QDockWidget(title, self)
        dock.setWidget(widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt override
        """Persist theme and window layout before the window closes."""
        # The runtime theme toggle is transient until now; capture it here so it
        # survives a restart without writing to disk on every toggle.
        self._config = self._config.with_overrides(theme=self._theme_manager.current)
        try:
            save_config(self._config)
            settings = QSettings()
            if self._config.remember_window_geometry:
                settings.setValue("geometry", self.saveGeometry())
                settings.setValue("windowState", self.saveState())
            else:
                # Disabled: clear any stored layout so it does not linger.
                settings.remove("geometry")
                settings.remove("windowState")
        except OSError:
            logger.exception("Failed to persist settings on close")
        super().closeEvent(event)

    def _on_toggle_theme(self) -> None:
        """Cycle to the next theme and report the result in the status bar."""
        new_theme = self._theme_manager.toggle()
        display = self._theme_manager.display_name(new_theme)
        self.statusBar().showMessage(f"Theme: {display}", 3000)

    def _on_look_feel_selected(self) -> None:
        """Apply the theme chosen from the Look & Feel submenu."""
        action = self._look_feel_group.checkedAction()
        if action is not None:
            key = action.data()
            if key != self._theme_manager.current:
                self._theme_manager.apply(key)
                display = self._theme_manager.display_name(key)
                self.statusBar().showMessage(f"Theme: {display}", 3000)

    def _on_theme_changed(self, theme: str) -> None:
        """Re-render all molecule depictions with the palette matching ``theme``."""
        dark = self._theme_manager.is_dark
        self._table_panel.set_dark(dark)
        self._structure_panel.set_dark(dark)
        self._scaffold_panel.set_dark(dark)
        self._conformer_panel.set_dark(dark)
        self._viewer_3d_panel.set_dark(dark)
        self._space_panel.set_dark(dark)
        self._repro_panel.set_dark(dark)
        # Keep the Look & Feel checkmarks in sync.
        action = self._look_feel_actions.get(theme)
        if action is not None:
            action.setChecked(True)

    def _on_convert(self) -> None:
        """Open the file-format converter dialog."""
        ConverterDialog.run_converter(self)

    def _on_manual(self) -> None:
        """Show the user manual (non-modal, so the app stays usable alongside)."""
        if self._manual_dialog is None:
            self._manual_dialog = ManualDialog(self)
        self._manual_dialog.show()
        self._manual_dialog.raise_()
        self._manual_dialog.activateWindow()

    def _on_about(self) -> None:
        """Display the About dialog with developer and organization info."""
        # Build the developer credits section from constants.DEVELOPERS.
        dev_lines: list[str] = []
        for dev in constants.DEVELOPERS:
            emails = dev.get("emails", [])
            email_links = ", ".join(f'<a href="mailto:{e}">{e}</a>' for e in emails)
            dev_lines.append(f"<b>{dev['name']}</b><br/>{email_links}")
        developers_html = "<br/><br/>".join(dev_lines)

        QMessageBox.about(
            self,
            f"About {constants.APP_NAME}",
            f"<h3>{constants.APP_NAME} {constants.APP_VERSION}</h3>"
            f"<p>{constants.APP_DESCRIPTION}</p>"
            f"<hr/>"
            f"<p><b>Organization:</b> {constants.ORG_NAME}<br/>"
            f'<a href="{constants.ORG_URL}">{constants.ORG_URL}</a></p>'
            f"<hr/>"
            f"<p><b>Developers:</b></p>"
            f"<p>{developers_html}</p>"
            f"<hr/>"
            f"<p>License: {constants.LICENSE}</p>"
            f'<p><a href="{constants.PROJECT_URL}">{constants.PROJECT_URL}</a></p>',
        )
