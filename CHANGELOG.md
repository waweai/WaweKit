# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Branding.** The WaweKit logo (`WaweKit.png`) is now the application
  identity: window/taskbar icon (badge crop), a multi-resolution
  `resources/icons/wawekit.ico` baked into the PyInstaller build, and a
  **splash screen** showing the logo for ~2.5 s at startup before the main
  window appears.
- **Help → User Manual (F1).** A complete illustrated in-app manual
  (`resources/manual/`): quick start, every feature explained in plain
  language (what it does / when to use it / numbered steps / tips), 15
  screenshots, a full shortcut table, and troubleshooting. Ships inside the
  package and the frozen bundle; rendered in a non-modal QTextBrowser so
  users can follow along in the app. 6 new tests, including one that fails
  if the manual ever references a missing image or drops a feature section.

### Fixed
- **Gap analysis (4 correctness bugs, all in the research-track display
  path):**
  - `ReproducibilityMetrics.n_labile` was derived as
    `round(n · (1 − min(score)))` — the *larger* of the two per-identity
    labile counts, not the union that `is_labile` actually means, so the
    "N labile" shown in the panel, status bar, and benchmark could
    under-report. It is now the exact count carried from the run.
  - A protocol **failure** was counted as divergence: one failed protocol
    made a molecule "labile" with no real disagreement, and a molecule
    *every* protocol failed on compared as perfectly reproducible. Agreement
    is now judged only across protocols that produced a value; failures are
    tracked separately (`n_failed`/`all_failed`/`n_with_failures`) and
    surfaced in the panel headline, benchmark summary, and CSV
    (`n_failed_protocols` column).
  - Pairwise protocol agreement counted two failures (`"" == ""`) as a
    match, inflating the heatmap; only molecule pairs where both forms are
    valid now count, with the denominator adjusted accordingly.
  - The Reproducibility panel's placeholder pointed to the wrong menu
    ("Chemistry → …" — the action lives in **Research**).
  - 4 regression tests pin all of the above.
- **Manual accuracy pass.** The illustrated manual had drifted from the app
  it documents: `Ctrl+T` was described as a dark/light toggle in three places
  even though it now cycles through 8 Look & Feel themes; the "main window"
  tour was missing the Property Filters and standalone 3D Viewer tabs added
  since the manual was first written; and there was no mention of the View
  menu (the only place to restore an accidentally-closed panel). All fixed
  and cross-checked against the current menu-building code, not guessed.
- **Structural alerts no longer stutter the table.** PAINS/Brenk/NIH
  checking (`services/chemistry/alerts.py`) was triggered from the table's
  `data()` method — meaning the *first paint* of every row ran several
  hundred SMARTS-pattern matches synchronously on the GUI thread. Added
  `compute_alerts_for_records` (mirrors `compute_descriptors`'s batch/cache/
  progress shape exactly) and run it as an automatic background pass after
  every load, standardize, and batch — self-chaining so records added while
  a pass is already running still get picked up, with a termination
  condition so it cannot loop forever once nothing is left to check.
  `MoleculeRecord` gained `alerts_computed` (a non-triggering cache check)
  and `invalidate_alerts()`; the table now shows a blank/pending cell instead
  of blocking until the background pass fills it in. 15 new tests; verified
  end-to-end with a real background QApplication run (cells start pending,
  fill in without blocking, worker slot clears on completion).
- **Test-suite visibility regression from the earlier segfault workaround.**
  The `os._exit()` fix for the QtWebEngine shutdown crash (see the 0.1.0
  entry) was hooked to `pytest_sessionfinish`, but the terminal reporter
  prints its "FAILURES" / "N passed" summary from a *hookwrapper* around that
  same hook — hookwrapper post-yield code runs only after every plain
  hookimpl returns, so the exit fired before the summary ever printed. Any
  run with a failure showed no detail at all, just exit code 1. Moved the
  exit to `pytest_unconfigure`, which fires strictly after
  `pytest_sessionfinish` (and everything it wraps) completes — full failure
  output is back, exit code is still correct (verified 3 consecutive full
  runs, exit 0 every time; explicit failure-detail check also verified with
  a temporarily broken test).

## [0.1.0] - 2026-07-18

First public release: all 20 roadmap modules plus the 6-stage
standardization-reproducibility research track.

### Added
- **Module 20 — Release preparation.** `RELEASE_NOTES.md`; README status
  line updated (it still described Modules 1–8 only); this CHANGELOG
  converted from a single running `[Unreleased]` block into a dated `0.1.0`
  entry per Keep a Changelog convention.
- **Module 19 — Testing (CI).**
  - `.github/workflows/ci.yml`: runs on Ubuntu/Windows/macOS for every push
    and PR — `ruff check`, `black --check`, then the full `pytest` suite.
    Qt runs headless via the existing `QT_QPA_PLATFORM=offscreen` default in
    `tests/conftest.py`; Linux additionally installs the system Qt libraries
    PySide6 needs even to import without a display.
  - Fixed a real bug this surfaced: the test process was **segfaulting
    during interpreter shutdown** after all 300+ tests already passed (a
    known QtWebEngine/Chromium teardown crash — the 3D conformer viewer,
    Module 9). `pytest`'s exit code would have been non-zero, failing CI
    on every green run. Fixed with a `trylast` `pytest_sessionfinish` hook
    in `conftest.py` that flushes output and calls `os._exit(exitstatus)`
    once pytest has already recorded the real result, skipping the crashing
    native teardown entirely. Verified across 4 consecutive full-suite runs
    (exit code 0 every time; previously 139/access-violation).
- **Module 18 — Documentation.**
  - `mkdocs.yml`: a minimal MkDocs site over the existing `docs/` (Home,
    Features, Packaging), built and verified with `mkdocs build --strict`
    (zero warnings after fixing one broken anchor link in `FEATURES.md`).
- **Module 17 — Packaging.**
  - `wawekit.spec`: a hand-written PyInstaller spec (not the naive one-liner) —
    explicitly bundles the three things static import analysis misses: SVG
    icons + QSS themes + vendored 3Dmol.js (read via `importlib.resources`,
    never `import`-ed), RDKit's own data files, and hidden submodules for
    RDKit/scikit-learn/matplotlib's Qt backend. `UPX` disabled deliberately
    (a frequent source of AV false-positives and Qt/RDKit startup crashes).
    Build with `pyinstaller wawekit.spec`; `pyinstaller` added to the `dev`
    extra.
- **Module 16 — Plugin system.**
  - `plugins/base.py`: `WawekitPlugin`, a `runtime_checkable` `Protocol`
    (`name`, `version`, `activate(context)`) — a plugin author depends on
    matching a shape, not on importing the app. `PluginContext` exposes only
    `add_menu_action`/`add_dock`, a deliberately narrow extension surface.
  - `plugins/manager.py`: discovery via Python entry points (group
    `wawekit.plugins`, the same mechanism `pip` itself uses for console
    scripts) — no new dependency. `load_plugins` applies the same resilience
    rule as every chemistry service in this app: one bad plugin (bad import,
    bad constructor, exception in `activate()`) is logged and skipped, never
    crashes the app.
  - `MainWindow._load_plugins()`: a **Plugins** menu, empty at startup,
    populated by whatever plugins are discovered.
  - Verified end-to-end with a real installed third-party-style package
    (`examples/example-plugin/`, `pip install -e`), not just mocks — genuine
    `importlib.metadata` discovery produced a working "Say Hello" menu item.
    6 new tests.
- **Research flagship R2–R6 — Divergence analysis, metrics, GUI, benchmark, manuscript.**
  - `services/reproducibility/divergence.py`: `analyze_molecule`/`analyze_divergence`
    — per-molecule agreement on both identity conventions plus **ablation-based
    cause attribution** (toggle each operation off; the first that changes the
    outcome is the implicated cause).
  - `services/reproducibility/metrics.py`: `compute_metrics` — reproducibility
    score, pairwise protocol-agreement matrix, and divergence cause spectrum.
  - `gui/widgets/reproducibility_panel.py` + `gui/dialogs/reproducibility_dialog.py`:
    a new **Research** menu → Reproducibility Audit — protocol-agreement heatmap,
    cause-spectrum chart (Matplotlib, exportable), and a labile-molecule list.
  - `services/reproducibility/benchmark.py`: a Qt-free CLI benchmark harness
    (`python -m wawekit.services.reproducibility.benchmark`), run for real on a
    40-molecule illustrative set: 70.0% SMILES-reproducible, 75.0%
    InChIKey-reproducible; dominant causes charge (41.7%) and salt/fragment
    handling (33.3%). Results captured in `learning/research-track-R5-benchmark/`.
  - A full manuscript draft (Abstract → Conclusion) populated with the real
    benchmark numbers at `learning/research-track-R6-manuscript/manuscript_draft.md`.
  - 23 new tests (divergence 9, metrics 7, benchmark 7).
- **Research flagship R1 — Standardization protocol engine.**
  - `services/reproducibility/protocol.py`: `StandardOp` (8 toggleable operations),
    `StandardizationProtocol` (a named operation set applied in a fixed order,
    with `with_op` ablation), presets (`Minimal`/`ChEMBL-like`/`Aggressive`), and
    the engine — `apply_protocol`, `standard_identity` (InChIKey), `standardize`
    → `StandardForm` (carries both canonical SMILES and InChIKey).
  - First finding: the canonical-tautomer operation changes the SMILES form but
    **not** the InChIKey (InChI normalizes tautomers), so SMILES- and
    InChIKey-identity disagree on which molecules are pipeline-dependent — the
    divergence study measures both. (12 tests; a demo script + captured output.)
- **Module 15 — Settings.**
  - `core/config.save_config` — a dependency-free TOML writer (the config is a
    flat table; `bool` serialized before `int` so `True` → `true`, not `1`).
  - `SettingsDialog` — a pure editor (config in, config out) for theme, log level
    and the remember-layout toggle, with Restore Defaults; changes apply live and
    persist to `<config_dir>/settings.toml`.
  - Window geometry + dock layout persisted via `QSettings`
    (`saveGeometry`/`saveState` on close, restored on start when enabled); theme
    captured on close so `Ctrl+T` survives a restart without per-toggle writes.
  - File → Settings (Ctrl+,); settings icon.
- **Module 14 — Report generation.**
  - `services/reporting/`: `build_summary` (format-independent stats, honest
    about partial analysis) + `generate_report` dispatching to two writers that
    share the same summary, so HTML and PDF never disagree.
  - `html_writer` — self-contained HTML with **inline SVG** depictions, a
    descriptor Min/Mean/Max table, a molecule grid, and print CSS.
  - `pdf_writer` — paginated A4 PDF via ReportLab; depictions rasterized by the
    new **`render_png`** (RDKit Cairo, Qt-free) so the whole report runs in the
    worker. `render_svg`/`render_png` now share a private `_draw` helper.
  - `ReportDialog` (title, HTML/PDF checkboxes, depiction toggle, molecule cap,
    base output path); an **Open** button on completion; File menu + toolbar.
  - Promoted `reportlab` from the `science` extra to a core dependency.
- **Module 13 — Batch processing.**
  - `services/batch.py`: `BatchConfig` (a serialisable recipe of frozen options),
    `run_batch` chaining standardize → descriptors → fingerprints → scaffolds →
    cluster → export in fixed order, and `BatchResult` with per-step summaries.
  - **Cancellation**: a `threading.Event` checked between steps and within them
    (via a wrapped progress callback); `BatchCancelled` derives from
    `BaseException` so the services' `except Exception` handlers cannot swallow it.
  - `services/io/molecule_exporter.py`: `export_csv` (identity + descriptors +
    annotations, blanks for uncomputed) and `export_sdf` (computed values as SD
    tags, set on a copy — `record.mol` never mutated). Reused by Module 14.
  - `BatchDialog` (step checklist + shared fingerprint encoding + export target);
    a non-modal Cancel button in the status bar; `_reset_derived_views()`
    extracted from the standardize handler and shared. Chemistry menu + toolbar.
- **Module 12 — Substructure search.**
  - `models/substructure.py`: `SubstructureQuery` and `SubstructureHit` (carries
    its query + matched atom indices — query-relative, like a similarity score).
  - `services/chemistry/substructure.py`: `parse_query` (SMARTS/SMILES, mutes
    stderr, returns `None`) and `search_substructure` → `SubstructureReport`.
  - **`render_svg` gained `highlight_atoms`** (the first renderer extension):
    highlights the matched atoms *and* the bonds between them, in both the table
    thumbnails (match folded into the delegate cache key) and the Structure panel.
  - Sortable "Substructure" column (`✓ N` / `—` / blank) and a fourth AND-ed
    filter channel (`SubstructureFilter`, "show only matches"); the proxy's
    `filterAcceptsRow` refactored to iterate its active channels.
  - `SubstructureDialog` with live SMARTS/SMILES validation; Chemistry menu +
    toolbar action + substructure icon.
- **Module 11 — Clustering.**
  - `models/clustering.py`: `ClusterMethod` (Butina/K-Means), `ClusterRun`, and
    `ClusterAssignment` (carries its run — a cluster id is dataset-relative, like
    a similarity score).
  - `services/chemistry/clustering.py`: `ClusterOptions` and `cluster_molecules`
    → `ClusterReport`. Butina (RDKit `ML.Cluster`, Tanimoto distance, cutoff) and
    K-Means (scikit-learn, lazy import); clusters numbered largest-first; ensures
    fingerprints first; assignments cached in place, stale ones cleared.
  - Sortable "Cluster" table column (with provenance tooltip) + a categorical
    "colour by Cluster" mode in the chemical-space scatter (tab20, no colourbar),
    auto-selected after a run so families light up on the map.
  - `ClusteringDialog` (method + reused `FingerprintOptionsWidget` — 4th consumer
    + Butina cutoff / K-Means K); Chemistry menu + toolbar action + cluster icon.
- **Module 10 — Chemical space visualization.**
  - `services/chemistry/chemical_space.py`: `ProjectionMethod` (PCA/t-SNE),
    `SpaceOptions`, `ProjectionPoint`/`ProjectionResult`, and `project` — ensures
    fingerprints, builds the bit matrix, reduces to 2D with scikit-learn (imported
    lazily). A projection is dataset-relative, so it is never cached on records.
  - Interactive Matplotlib scatter (`ChemicalSpacePanel`, bottom dock) with the
    navigation toolbar (pan/zoom/export), colour-by any descriptor or similarity
    (missing values grey), hover tooltips, and click/lasso selection.
  - Two-way link: plot selection → `MoleculeTablePanel.select_records`; table
    selection → `highlight_records` (rings points in place, no feedback loop).
  - `ChemicalSpaceDialog` (method + reused `FingerprintOptionsWidget` + t-SNE
    perplexity); Chemistry menu + toolbar action + `chemspace` icon.
  - Promoted `matplotlib` and `scikit-learn` from the `science` extra to core
    dependencies (Modules 10 and 11 make them load-bearing).
- **Module 9 — Conformer generation** (first 3D feature).
  - `models/conformers.py`: `ForceField` (MMFF94/UFF/None), `ConformerOptions`,
    `Conformer`, and `ConformerSet` — the 3D geometry lives on
    `ConformerSet.mol_3d` (a separate H-added molecule), never on `record.mol`.
  - `services/chemistry/conformers.py`: `generate_conformers` → `ConformerReport`
    via RDKit ETKDGv3 embedding + MMFF94/UFF optimisation (auto UFF fallback when
    MMFF params are missing) + energy ranking + RMSD-to-lowest; seeded for
    reproducibility; cache-in-place.
  - Interactive 3D viewer: `ConformerView` embeds vendored **3Dmol.js** (BSD-3,
    offline, inlined) in a `QWebEngineView`; `ConformerPanel` follows the table
    selection and shows the energy/ΔE/RMSD table with **SDF export**.
  - `ConformerDialog` (n_confs, force field, prune RMSD, seed); Chemistry menu +
    toolbar action. Generation runs on the selection when there is one, else the
    whole dataset (it is far heavier than the 2D operations).
  - Vendored `resources/web/3Dmol-min.js` + attribution `NOTICE-3Dmol.txt`.
- **Module 8 — Scaffold analysis.**
  - `models/scaffold.py`: `ScaffoldResult` (exact Murcko + generic-framework
    SMILES + `has_ring_system`) and `ScaffoldRepresentation` (Murcko/Generic).
    Acyclic molecules are represented honestly as an empty scaffold, not a crash.
  - `services/chemistry/scaffolds.py`: `compute_scaffolds` (cache-in-place, the
    descriptors pattern) → `ScaffoldReport`; `group_scaffolds` → `ScaffoldGroup`
    list ranked by member count (scaffold diversity).
  - Scaffolds dock panel: diversity headline, exact/generic toggle, ranked
    scaffold list with rendered thumbnails, and click-to-filter. Emits intent
    only (no worker/RDKit in the widget).
  - Sortable "Scaffold" column in the table (sorting clusters shared scaffolds).
  - Scaffold filtering added as a second, AND-ed channel on the filter proxy
    (`ScaffoldFilter`) so a scaffold selection combines with the text query;
    Chemistry menu + toolbar action + scaffold icon.
- **Module 7 — Similarity search.**
  - `models/similarity.py`: `SimilarityMetric` (Tanimoto/Dice/Cosine),
    `SimilarityQuery` (query identified by canonical SMILES, its metric and
    fingerprint options), and `SimilarityScore` (a value that carries its query
    — a similarity is relational, not an intrinsic molecule property).
  - `services/chemistry/similarity.py`: `search_similar` → `SimilarityReport`
    (ranked scores, skipped molecules, fingerprints computed as a side effect).
  - `SimilarityDialog` with live SMILES validation; right-click "Find Similar to
    This"; results land in a sortable "Similarity" column (query row bold), no
    threshold field — the quick-filter narrows scores after the fact (`Sim >= 0.7`).
  - `parse_smiles` loader helper (returns `None`, mutes RDKit stderr) so the
    dialog never imports RDKit. Fixed a latent dark-theme bug: checked
    `QRadioButton` rendered no indicator.
- **Module 6 — Fingerprints.**
  - `models/fingerprints.py`: `FingerprintKind` (Morgan/MACCS/RDKit),
    `FingerprintOptions` (with `normalized()` so identity = effective config),
    `Fingerprint` (carries the options that built it — different params are not
    comparable, so a re-run replaces rather than mixes).
  - `services/chemistry/fingerprints.py` on `rdFingerprintGenerator` (not the
    deprecated legacy API); `FingerprintReport`.
  - `FingerprintDialog` + extracted `FingerprintOptionsWidget`; "Fingerprint"
    column showing algorithm and set-bit count. Fixed a Qt-boundary bug: a
    `StrEnum` in combo item-data round-trips as a plain `str` (use `==`, not `is`).
- **Module 5 — Descriptors.**
  - `models/descriptors.py`: frozen `DescriptorSet` (MW, LogP, TPSA, HBD/HBA,
    RotB, rings + Lipinski verdict) and `DESCRIPTOR_SPECS` — the single source of
    truth driving headers, cell formatting, sort keys, tooltips and filter tokens.
  - `services/chemistry/descriptors.py`: `compute_descriptors` → `DescriptorReport`;
    values cached on records in place (a descriptor is a cache, not a new molecule),
    with an in-place column repaint that preserves scroll and selection.
  - Quick-filter box: custom `MoleculeFilterProxyModel` with a tiny query language
    (`aspirin`, `MW < 500`, `Sim >= 0.7`) that compares typed values, not text;
    unparseable queries are reported, never silently ignored.
- **Module 4 — Molecular standardization.**
  - Configurable pipeline service (`standardize_records`) on RDKit
    `rdMolStandardize`: Cleanup, salt stripping (largest fragment), charge
    neutralization, canonical tautomer, and duplicate removal by standardized
    canonical SMILES. Immutable-in/new-out; per-record failure resilience;
    full `StandardizationReport` provenance (what changed, dups, failures).
  - `StandardizeDialog` (checkbox pipeline picker, static `get_options` factory).
  - Chemistry menu + toolbar action; runs on the shared `FunctionWorker` with
    progress; results replace the dataset with a change-summary dialog.
- **Polish rider.**
  - Hand-authored SVG icon set (`resources/icons/`) + `icons.get_icon` loader
    (importlib.resources, multi-size, cached); app/window icon; toolbar icons.
  - Right-click context menu on the molecule table (Copy SMILES, Copy Names,
    Remove Selected); `set_records`/`remove_rows` on the model.
  - Capped SMILES column width so Formula/Heavy atoms/Source stay visible.
- **Module 3 — Molecule viewer.**
  - Qt-free SVG renderer service (`render_svg`) with dark-mode palette,
    transparent background, and on-the-fly 2D coordinate generation.
  - Structure thumbnails inside the molecule table via a custom
    `QStyledItemDelegate` with HiDPI pixmap caching (renders visible cells only).
  - Structure dock panel: large scalable depiction, identity (name, formula,
    canonical SMILES), SDF properties table, Copy SMILES, Save Image (SVG/PNG).
  - Selection wiring (`selection_changed` signal) and theme-reactive rendering
    (`ThemeManager` is now a `QObject` emitting `theme_changed`).
  - View menu now uses `QDockWidget.toggleViewAction()` for both docks.

### Fixed
- Molecule table displayed rows in reverse load order: enabling sorting applied
  Qt's default descending sort indicator; the view now starts with an explicit
  ascending sort on the row-number column.
- Structure thumbnails bled into adjacent table cells: the delegate centered
  using the pixmap's *physical* pixel rect (2× oversampled) instead of its
  device-independent size; painting is now also clipped to the cell rect.
  Found by screenshot-driven visual inspection.
- **Module 2 — Molecule loading.**
  - `MoleculeRecord` domain model (RDKit `Mol` + name, provenance, SDF
    properties; cached canonical SMILES and formula).
  - Robust loader service for SDF, MOL and SMILES files with per-record error
    capture (`LoadReport`/`LoadError`) and progress callbacks; UI-free.
  - Reusable background-worker infrastructure (`FunctionWorker` on
    `QThreadPool`, signal-based results/progress).
  - Sortable molecule table (Qt Model/View: `QAbstractTableModel` +
    `QSortFilterProxyModel` + `QTableView`) as the central workspace.
  - File → Open dialog, window-wide drag-and-drop, sequential load queue,
    status-bar progress bar, error summary dialog, loaded-files list in the
    Workspace dock.
  - Table/list styling for both themes; loader and table test suites
    (18 tests total, all passing).
- **Module 1 — Project architecture.**
  - `src`-layout package `wawekit` with layered structure
    (`core`, `models`, `services`, `gui`, `plugins`, `resources`).
  - Core infrastructure: constants, cross-platform paths (`QStandardPaths`),
    typed `AppConfig` with layered TOML loading, and rotating-file logging.
  - Themed desktop shell: `MainWindow` with menu bar, toolbar, status bar and a
    dockable workspace panel; runtime dark/light theme switching via QSS.
  - Composition root (`app.run`) and `python -m wawekit` entry point.
  - Packaging (`pyproject.toml`, hatchling), console script `wawekit`.
  - Tooling config for black, ruff, pytest.
  - Smoke test suite (`pytest` + `pytest-qt`, offscreen).
  - Open-source docs: README, CONTRIBUTING, CODE_OF_CONDUCT, MIT LICENSE.
  - Learning artifacts: graphical abstract + notes under `learning/`.
