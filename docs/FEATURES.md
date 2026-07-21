# Wawekit — Feature Reference

A complete reference to every feature in Wawekit: what it is, why it matters,
where it's used in real research, how it works internally, and the step-by-step
workflow to use it. Organized in build order (Module 1 → 15, then the research
track). Each feature builds on the ones before it.

For build history, design rationale and screenshots, see the matching folder
under [`learning/`](../learning/). This document is the *what/why/how*; `learning/`
is the *how it was built*.

---

## Table of contents

1. [Project Architecture](#1-project-architecture)
2. [Molecule Loading](#2-molecule-loading)
3. [Molecule Viewer](#3-molecule-viewer)
4. [Molecular Standardization](#4-molecular-standardization)
5. [Descriptors](#5-descriptors)
6. [Fingerprints](#6-fingerprints)
7. [Similarity Search](#7-similarity-search)
8. [Scaffold Analysis](#8-scaffold-analysis)
9. [Conformer Generation (3D)](#9-conformer-generation-3d)
10. [Chemical Space Visualization](#10-chemical-space-visualization)
11. [Clustering](#11-clustering)
12. [Substructure Search](#12-substructure-search)
13. [Batch Processing](#13-batch-processing)
14. [Report Generation](#14-report-generation)
15. [Settings](#15-settings)
16. [Research Track — Standardization Reproducibility Auditor](#16-research-track-standardization-reproducibility-auditor)

---

## 1. Project Architecture

**What it is:** The foundational layered structure of the whole application —
not a user-facing feature, but the skeleton every other feature depends on.
Four layers (`core → models → services → gui`) with a strict rule: a layer may
only import from the layers below it.

**Why it's useful:** Without this discipline, a 20-feature cheminformatics app
turns into an unmaintainable tangle within a few modules. The layering is what
lets every chemistry operation in this document run **headlessly** — in a test,
a Jupyter notebook, or a batch script — with zero GUI dependency.

**Where it's used / applications:** Invisible to the end user, but it is *why*
every feature below can be scripted, tested, and reused outside the desktop app
(e.g. the research benchmark harness in §16 reuses the exact same services the
GUI calls).

**Mechanism:**
- `core` — configuration, logging, cross-platform paths, constants. Depends on nothing.
- `models` — plain Python + RDKit domain objects (`MoleculeRecord` and friends). No Qt.
- `services` — the actual chemistry (RDKit calls) and orchestration (background
  workers). May use Qt's non-visual `QtCore` (signals, threads) but never widgets.
- `gui` — PySide6 windows, dialogs, panels. The only layer allowed to import `QtWidgets`.
- A composition root (`app.py`) wires config → logging → theme → window at startup.

**Workflow:** N/A — this is architecture, not an interactive feature.

---

## 2. Molecule Loading

**What it is:** Import molecules into the app from SDF, MOL, or SMILES files,
via *File → Open* or drag-and-drop, with background-threaded parsing and
per-record error recovery.

**Why it's useful:** Real chemical files are dirty — a 10,000-molecule vendor
SDF often has a handful of unparseable records. A naive loader crashes or
silently drops data; Wawekit loads everything it can and **reports exactly
which records failed and why**, so you never lose data silently.

**Where it's used / applications:** The entry point for every workflow — loading
a screening library, a vendor catalog, a set of literature compounds, or a
ChEMBL/PubChem export.

**Mechanism:**
- Format dispatch by extension: `.sdf` → `Chem.SDMolSupplier`, `.mol` →
  `Chem.MolFromMolFile`, `.smi`/`.smiles`/`.txt` → line-by-line `MolFromSmiles`.
- Each record is wrapped in error handling; a failure becomes a `LoadError`
  (location + message), not a crash.
- Parsing runs on a background thread (`FunctionWorker` on `QThreadPool`) so the
  UI stays responsive; a progress bar tracks records processed.
- Successful records become `MoleculeRecord` objects (RDKit `Mol` + name +
  source path + SDF properties) and populate the molecule table.

**Workflow:**
1. **File → Open Molecules…** (or drag a file onto the window).
2. Watch the progress bar as the file parses.
3. Loaded molecules appear in the central table; any errors show in a summary
   dialog with per-record detail.
4. The source file is listed in the **Workspace** dock.

---

## 3. Molecule Viewer

**What it is:** 2D structure depictions everywhere a molecule appears — small
thumbnails in every table row, and a large interactive view in the **Structure**
dock for the selected molecule, with SVG/PNG export.

**Why it's useful:** Chemists think in structures, not SMILES strings. Seeing
the molecule — not just its formula — is what turns a spreadsheet into a
cheminformatics tool.

**Where it's used / applications:** Visual triage of a screening set, quick
sanity-checking after loading, preparing a structure image for a slide or paper
(via *Save Image…*).

**Mechanism:**
- `render_svg()` — a Qt-free RDKit service (`rdMolDraw2D.MolDraw2DSVG`) that
  generates 2D coordinates if missing, applies a dark/light palette, and returns
  an SVG string. Later extended with `render_png()` (RDKit's Cairo backend) for
  raster output (used by PDF reports, §14).
- Table thumbnails are painted by a custom `QStyledItemDelegate`, cached by
  (SMILES, highlight) key so scrolling a 100k-row table only renders visible
  cells.
- The Structure panel shows the selection via a Qt `QSvgWidget`, with **Copy
  SMILES** and **Save Image…** (SVG or high-res PNG) actions.
- Everything re-renders automatically when the theme toggles (dark ↔ light).

**Workflow:**
1. Load molecules (§2) — thumbnails appear immediately in the table.
2. Click any row → the **Structure** panel shows a large depiction with name,
   formula, canonical SMILES and any SDF properties.
3. **Copy SMILES** to clipboard, or **Save Image…** to export SVG/PNG.

---

## 4. Molecular Standardization

**What it is:** A configurable cleanup pipeline — strip salts, neutralize
charges, canonicalize tautomers, remove duplicates — applied to the whole
dataset before any downstream analysis.

**Why it's useful:** Descriptors, fingerprints, and clustering computed on
unstandardized data are **silently wrong**: `CC(=O)Oc1ccccc1C(=O)[O-].[Na+]`
(aspirin sodium salt) and `CC(=O)Oc1ccccc1C(=O)O` (aspirin) will be treated as
different molecules unless standardized first. Every serious pipeline
(ChEMBL curation, pharma registration systems) standardizes before anything else.

**Where it's used / applications:** Cleaning a vendor library before screening,
merging datasets from different sources so identical compounds collapse
together, preparing data for machine learning where duplicate/inconsistent
structures bias models.

**Mechanism:**
- Built on RDKit's `rdMolStandardize`: `Cleanup` (normalize representations),
  `LargestFragmentChooser` (salt/solvent stripping), `Uncharger` (charge
  neutralization), `TautomerEnumerator.Canonicalize` (tautomer canonicalization
  — expensive, opt-in), then deduplication by canonical SMILES.
- Each step is independently toggleable via `StandardizationOptions`.
- Produces **new** `MoleculeRecord` objects (chemistry changed → new identity),
  with a full `StandardizationReport`: before/after SMILES for every changed
  molecule, duplicate count, and per-molecule failures — never a silent change.

**Workflow:**
1. **Chemistry → Standardize…**
2. Tick the steps to apply (all on by default except tautomer canonicalization).
3. Run — a progress bar tracks the dataset.
4. Review the change summary (what changed, what was removed) in the results
   dialog; the table updates to the cleaned dataset.

---

## 5. Descriptors

**What it is:** The classic drug-likeness numeric panel computed per molecule —
molecular weight, LogP, TPSA, H-bond donors/acceptors, rotatable bonds, ring
count, and a derived Lipinski "Rule of 5" verdict.

**Why it's useful:** These are the standard first-pass filters in drug
discovery. A medicinal chemist scanning a library asks "how many pass
Lipinski?" before anything else; these descriptors are also the inputs to most
downstream QSAR/ML work.

**Where it's used / applications:** Library triage, oral-bioavailability
screening, as filter/sort criteria in the quick-filter box (`MW < 500`), and as
the statistical backbone of generated reports (§14).

**Mechanism:**
- RDKit `Descriptors.MolWt/MolLogP/TPSA/NumHDonors/NumHAcceptors/NumRotatableBonds`
  and `rdMolDescriptors.CalcNumRings`.
- Cached **in place** on each `MoleculeRecord` (a descriptor is a pure function
  of structure, so it's a cache, not a new molecule) — the table repaints just
  the descriptor columns, preserving scroll position and selection.
- `DESCRIPTOR_SPECS` is the single source of truth: adding a descriptor there
  automatically updates table columns, tooltips, sort keys, filter tokens, and
  report tables.
- A quick-filter text box (`MW < 500`, `LogP > 2`) filters the table live using
  these cached values — no recomputation.

**Workflow:**
1. **Chemistry → Compute Descriptors** (runs over the whole dataset in the
   background).
2. New columns (MW, LogP, TPSA, HBD, HBA, RotB, Rings, Lipinski) populate the
   table.
3. Type a filter like `MW < 500` or `Lipinski = 0` in the box above the table
   to narrow the view.

---

## 6. Fingerprints

**What it is:** Encode each molecule's structure as a fixed-length bit vector
(Morgan/ECFP, MACCS keys, or RDKit path-based), the representation that makes
similarity search, clustering, and chemical-space mapping computationally
possible.

**Why it's useful:** You cannot ask "how similar are these two molecules?" or
"which cluster does this belong to?" without first turning structures into
vectors that support fast mathematical comparison (Tanimoto, Euclidean, etc.).
Fingerprints are the universal input to virtual screening.

**Where it's used / applications:** The encoding layer beneath similarity
search (§7), chemical space (§10), and clustering (§11) — every one of those
features calls this one first.

**Mechanism:**
- **Morgan (ECFP)** — circular fragments around each atom out to a radius,
  hashed into N bits; the field's default for similarity work. Optional
  "feature" mode (FCFP) matches by pharmacophore role instead of exact element.
- **MACCS** — 166 fixed, interpretable structural keys (no parameters).
- **RDKit** — Daylight-style hashed linear paths.
- Built via RDKit's modern generator API (`rdFingerprintGenerator`), with the
  (expensive) generator constructed once per run, not per molecule.
- A `Fingerprint` carries the **normalized options that produced it** — two
  fingerprints are only comparable if built with identical parameters, so the
  cache rule is "reuse only if params match," preventing silent mixing of
  incompatible vectors.

**Workflow:**
1. **Chemistry → Compute Fingerprints…**
2. Choose the algorithm (Morgan is the default) and parameters (radius, bit
   size, features).
3. Run — a **Fingerprint** column shows algorithm + bits-set summary per row
   (hover for full parameters).

---

## 7. Similarity Search

**What it is:** Rank every molecule in the dataset by structural similarity to
one query molecule — either a row you select or a SMILES you paste — using
Tanimoto, Dice, or Cosine similarity on fingerprints.

**Why it's useful:** *"Find me more compounds like this hit"* is the
single most common operation in a medicinal chemist's day — the core of
similarity-based virtual screening and hit expansion.

**Where it's used / applications:** Expanding a screening hit into an analog
series, searching an in-house library against a literature compound, triaging
a large set by relevance to a reference structure.

**Mechanism:**
- A similarity score is **relational**, not intrinsic — 0.62 means nothing
  without "vs which query, by which metric, on which fingerprint." So
  `SimilarityScore` always carries its `SimilarityQuery`, and the table shows
  the score with hover-context, never a bare number.
- Query resolution: the selected table row, or a pasted SMILES validated live
  as you type (parsed via a Qt-free `parse_smiles` helper so the dialog never
  imports RDKit directly).
- Scoring uses RDKit's `BulkTanimotoSimilarity` (and Dice/Cosine equivalents)
  against every fingerprint in the dataset; incompatible fingerprints are
  detected and reported rather than silently compared.
- No threshold field on the dialog by design — scores land in a **sortable
  column**, and the existing quick-filter box narrows results afterward
  (`Sim >= 0.7`), avoiding a "guess the right cutoff before you see the data"
  workflow.

**Workflow:**
1. Select a molecule in the table (or leave nothing selected to paste a query).
2. **Chemistry → Similarity Search…**
3. Confirm/paste the query, choose a metric and fingerprint encoding → Search.
4. The table sorts by similarity (best first); the query row is bolded.
5. Filter with `Sim >= 0.7` to narrow to close analogs.

---

## 8. Scaffold Analysis

**What it is:** Reduce every molecule to its Bemis–Murcko scaffold (core ring
systems + linkers, side chains stripped) and group the dataset by shared
scaffold to reveal **scaffold diversity**.

**Why it's useful:** "How many distinct chemical series are actually in this
500-compound set?" — a library that collapses to 12 scaffolds is far less
diverse than one with 300, and this number drives library-design and
lead-selection decisions directly.

**Where it's used / applications:** Assessing screening-library diversity,
identifying chemical series in a hit list, spotting over-representation of one
scaffold in a dataset.

**Mechanism:**
- `MurckoScaffold.GetScaffoldForMol` (exact scaffold, atom/bond types kept) and
  `MakeScaffoldGeneric` (all-carbon, single-bond framework — groups more
  aggressively; e.g. pyridine and benzene cores merge).
- Acyclic molecules (no ring system) are handled honestly as their own
  `(acyclic)` group, never crashed on or fabricated.
- Two views of one computation: a sortable **Scaffold column** (sorting = free
  grouping in a flat table) and a **Scaffolds dock panel** — a diversity
  headline, an exact/generic toggle, and a ranked, thumbnail list of scaffolds
  by member count. Clicking a scaffold filters the table to its members.

**Workflow:**
1. **Chemistry → Analyze Scaffolds**.
2. The **Scaffolds** panel shows "*N molecules → M distinct scaffolds*" with
   thumbnails ranked by size.
3. Toggle **Murcko (exact)** vs **Generic framework** to see coarser grouping.
4. Click a scaffold to filter the main table to just its members.

---

## 9. Conformer Generation (3D)

**What it is:** Generate, energy-rank, and interactively view 3D conformers of
a molecule — the first 3D feature in the app, with a real rotatable WebGL
viewer and SDF export.

**Why it's useful:** 2D structures don't capture shape, and shape drives
binding. Conformer ensembles are a prerequisite for docking prep, 3D-QSAR, and
pharmacophore modeling.

**Where it's used / applications:** Preparing ligands for docking, exploring
conformational flexibility of a hit compound, exporting 3D coordinates for
external modeling tools.

**Mechanism:**
- RDKit's **ETKDGv3** distance-geometry embedding (`EmbedMultipleConfs`, seeded
  for reproducibility, RMSD-pruned to keep genuinely distinct shapes) followed
  by **MMFF94** force-field optimization (auto-falling-back to **UFF** when
  MMFF lacks parameters for an atom — never silently failing).
- The 3D geometry (with explicit hydrogens, multiple conformers) lives on a
  **separate** `ConformerSet.mol_3d`, never overwriting the 2D `record.mol` used
  by the table/Structure panel.
- Display: **3Dmol.js** (vendored, fully offline) inside a `QWebEngineView` —
  real rotate/zoom WebGL, not a static image.
- A per-conformer table (energy, ΔE from the lowest, RMSD to the lowest) sits
  beside the viewer; **Export SDF** writes every conformer with real 3D
  coordinates.
- Because embedding is heavy, it runs on the current **selection** if any,
  falling back to the whole dataset only when nothing is selected.

**Workflow:**
1. Select one or more molecules (or none, to process everything).
2. **Chemistry → Generate Conformers…** — set conformer count, force field, and
   pruning threshold.
3. The **Conformers** panel shows a rotatable 3D structure and the ranked
   energy table; click rows to view different conformers.
4. **Export SDF…** to hand the ensemble to docking/other tools.

---

## 10. Chemical Space Visualization

**What it is:** An interactive 2D scatter plot of the whole dataset — each
point a molecule, positioned by projecting its fingerprint down to 2D (PCA or
t-SNE) — with color-by-property, hover tooltips, and two-way selection linking
to the molecule table.

**Why it's useful:** A table of 500 rows tells you nothing about structure;
a map shows clusters, outliers, and diversity **at a glance**. This is the
standard way medicinal/computational chemists visually explore a library.

**Where it's used / applications:** Spotting structural clusters and outliers
in a screening set, visually assessing library diversity, exploring how a
property (LogP, cluster, similarity) is distributed across chemical space.

**Mechanism:**
- Ensures a consistent fingerprint encoding across the dataset (reusing §6),
  builds an (n_molecules × n_bits) matrix, and reduces it with **PCA** (linear,
  fast, deterministic, reports variance captured per axis) or **t-SNE**
  (non-linear, separates tight clusters, axes carry no global meaning).
- A projection is *dataset-relative* — like a similarity score, it depends on
  the whole set and the method — so it is **never cached on a record**; it lives
  only in the GUI panel and is recomputed/cleared when the dataset changes.
- Rendered with an embedded **Matplotlib** canvas, which brings a real
  navigation toolbar (pan/zoom/**export to PNG/PDF/SVG**) for free.
- **Color-by** any descriptor or the last similarity score (continuous, viridis
  colormap + colorbar) — missing values render grey, never a misleading zero.
- **Two-way linking**: click or lasso points in the plot to select those
  molecules in the table (Structure/Conformer panels follow); selecting rows in
  the table rings the matching points on the plot.

**Workflow:**
1. **Chemistry → Chemical Space…** — choose PCA or t-SNE and a fingerprint encoding.
2. The dataset renders as a scatter plot at the bottom of the window.
3. Hover points for identity; click or lasso-select a region to select those
   molecules; choose a **Colour by** dimension to paint the map by property.
4. Use the plot toolbar to zoom in on a cluster or export the figure.

---

## 11. Clustering

**What it is:** Group molecules by fingerprint similarity into discrete
clusters — via **Butina** (similarity-threshold, the cheminformatics standard)
or **K-Means** (fixed cluster count) — surfaced as a sortable table column and
a categorical color-by-cluster mode on the chemical-space map.

**Why it's useful:** "What families are actually in this library?" is the
clustering analogue of scaffold analysis, done on fingerprint similarity rather
than shared cores — useful for picking a diverse representative subset, or for
understanding how many distinct chemotypes a hit list contains.

**Where it's used / applications:** Diverse subset selection for follow-up
screening, structuring a large hit list into interpretable families, coloring
the chemical-space map to see clusters as visually distinct regions.

**Mechanism:**
- **Butina** — sphere-exclusion clustering on Tanimoto *distance*
  (`rdkit.ML.Cluster.Butina`): pick the molecule with the most neighbors within
  a cutoff as a cluster center, remove it and its neighbors, repeat. No cluster
  count to guess; dissimilar molecules become their own singleton clusters.
- **K-Means** — partitions the fingerprint bit-matrix into a fixed K
  (scikit-learn).
- Clusters are numbered **largest-first** (cluster 0 = biggest group) — a
  stable convention the table sort and the map's color palette both rely on.
- A cluster id is relational (depends on the whole dataset + method), so —
  like a similarity score — the `ClusterAssignment` carries its `ClusterRun`
  context and is cached on the record but actively cleared when stale.
- The chemical-space panel (§10) gained a **categorical** color mode
  specifically for cluster ids (a qualitative palette, no gradient/colorbar,
  because clusters are categories, not a scale).

**Workflow:**
1. **Chemistry → Cluster Molecules…** — choose Butina (with a similarity
   cutoff) or K-Means (with a target cluster count).
2. A **Cluster** column populates with each molecule's cluster id.
3. Sort the column to see cluster members grouped together, or open the
   Chemical Space panel — it auto-colors by cluster after a run.

---

## 12. Substructure Search

**What it is:** Find molecules that contain a specific structural fragment
(a SMARTS or SMILES pattern), with the matched atoms **highlighted** directly
in the table thumbnails and the large Structure panel.

**Why it's useful:** "Does this compound have a sulfonamide? An amide? A
particular ring system?" is a routine SAR and library-filtering question. Seeing
*where* the match is, not just that one exists, is what makes the result
actually useful.

**Where it's used / applications:** Filtering a library to compounds
containing/excluding a liability group, identifying which molecules share a
pharmacophore element, SAR analysis around a specific substructure.

**Mechanism:**
- Queries are parsed as **SMARTS** (the expressive query language — wildcards,
  recursive patterns, e.g. `[NX3][CX3](=O)` for an amide) or plain **SMILES**
  read as a query; the dialog validates the pattern live as you type.
- Matching via RDKit's `GetSubstructMatches(query, uniquify=True)`, recording
  every distinct match's atom indices.
- The renderer (`render_svg`, §3) gained a `highlight_atoms` parameter — the
  **first extension** to the shared depiction engine — highlighting matched
  atoms and the bonds between them so a match reads as one solid region.
- The table thumbnail cache key includes the match, so a new search
  automatically invalidates and re-renders only the affected thumbnails.
- A match is query-relative (like similarity/cluster results): `SubstructureHit`
  carries its query, and a **Substructure column** (`✓ N` / `—` / blank) plus an
  optional "show only matches" filter narrow the table.

**Workflow:**
1. **Chemistry → Substructure Search…**
2. Choose SMARTS or SMILES, type the pattern (validated live), optionally check
   "Show only matching molecules" → Search.
3. Matching molecules show the fragment **highlighted** in their thumbnails;
   select one to see the highlight in the large Structure panel.
4. The **Substructure** column and the quick-filter box narrow further.

---

## 13. Batch Processing

**What it is:** Chain any combination of the operations above (standardize →
descriptors → fingerprints → scaffolds → cluster) into one pipeline, run it
unattended over the whole dataset, and export the result to CSV or SDF — with
a cancel button for long runs.

**Why it's useful:** Running eight menu items one at a time on a 10,000-molecule
set is tedious and error-prone. Batch processing turns the whole analysis into
one configured, reproducible, cancellable operation — and produces the flat
file (CSV/SDF) that downstream tools (Excel, pandas, other software) actually need.

**Where it's used / applications:** Processing a full screening deck overnight,
producing an annotated CSV for a collaborator, running the same standardized
pipeline across multiple project datasets for consistency.

**Mechanism:**
- Every chemistry service was already built to one shape (Qt-free, takes a
  progress callback, returns a report), so the batch runner is almost pure
  composition: a list of steps, each calling one existing service in a fixed,
  chemically-sensible order (standardize first — it replaces records — export
  last).
- **Cancellation** — the first cancellable operation in the app. A
  `threading.Event` is checked between and within steps; the cancel signal
  (`BatchCancelled`) deliberately derives from `BaseException`, not `Exception`,
  so it cannot be accidentally swallowed by the per-molecule
  `except Exception` handlers every chemistry service uses to survive bad
  structures.
- A new export service writes **CSV** (identity + descriptors + annotations,
  blank for anything not computed) or **SDF** (computed values as SD tags on a
  copy of the molecule, never mutating the original record).
- `BatchConfig` is a frozen, serializable recipe (the same options objects every
  other feature already uses) — a foundation for reproducible pipelines.

**Workflow:**
1. **Chemistry → Batch Processing…**
2. Tick the steps to run and set their shared fingerprint encoding.
3. Choose an export format (CSV/SDF) and output path → Run.
4. Watch cumulative progress across the whole pipeline; **Cancel** stops it
   cleanly at the next safe point.
5. Review the per-step summary; the exported file is on disk.

---

## 14. Report Generation

**What it is:** Generate a shareable, research-ready summary of the dataset in
**both HTML and PDF** — a title, summary statistics, a descriptor table, and a
grid of molecule cards with structures and key properties.

**Why it's useful:** A screenshot of the app isn't something you attach to an
email or a supplement. A report is a self-contained artifact you can share with
a supervisor, embed in a paper's supporting information, or archive alongside a
dataset.

**Where it's used / applications:** Supporting information for a publication,
a project handoff summary, a snapshot of a screening campaign for
non-technical stakeholders.

**Mechanism:**
- One format-independent `ReportSummary` (molecule count, Lipinski pass rate,
  cluster/scaffold counts, per-descriptor min/mean/max — computed only from
  whatever *was* analyzed, silent about the rest) feeds **two writers**, so the
  two files can never disagree on a number.
- **HTML** — self-contained, molecule depictions embedded as inline SVG (crisp,
  no external files), styled with print CSS so it also prints cleanly to PDF
  from a browser.
- **PDF** — paginated A4 via ReportLab; depictions rasterized through a new
  Qt-free `render_png` (RDKit's Cairo backend), keeping the whole report
  pipeline off Qt so it runs entirely in a background worker.
- The molecule grid is capped for readability (configurable), but the summary
  statistics always cover the **entire** dataset.

**Workflow:**
1. **File → Generate Report…**
2. Set a title, choose HTML and/or PDF, whether to include depictions, and a
   molecule cap.
3. Browse to an output path → Generate.
4. Click **Open** on completion to view the result immediately.

---

## 15. Settings

**What it is:** Persistent user preferences — theme, log level, and window
size/position/dock layout — that survive an application restart, edited through
a Settings dialog.

**Why it's useful:** Re-arranging docks and re-selecting dark mode every single
launch is friction nobody should tolerate in professional software. This is the
"remembers how you like to work" feature.

**Where it's used / applications:** Every session, transparently — no direct
research application, but it's what makes the tool feel finished rather than a
prototype.

**Mechanism:**
- Two storage backends for two kinds of data: human-editable preferences (theme,
  log level) go to a hand-rolled TOML file (`<config_dir>/settings.toml` — no
  new dependency, since the config is a flat table of scalars); opaque window
  geometry/dock layout go to Qt's native `QSettings` (binary blobs from
  `saveGeometry`/`saveState`, not meant for hand-editing).
- The Settings dialog is a **pure editor** — it takes a config in and returns an
  edited copy out, never applying or saving itself; the main window owns that
  policy, keeping the dialog trivially testable.
- Settings save on dialog-OK (applied live: theme change repaints every panel)
  and on window close (captures the current runtime theme so a `Ctrl+T` toggle
  survives a restart without writing to disk on every keypress).

**Workflow:**
1. **File → Settings…** (or `Ctrl+,`).
2. Change theme, log level, or the "remember layout" toggle → OK (applies immediately).
3. Rearrange docks and resize the window as you like, then close the app.
4. Relaunch — the app reopens exactly as you left it.

---

## 16. Research Track — Standardization Reproducibility Auditor

**What it is:** A methods-research initiative (not a roadmap feature) building
toward a publishable finding: **structure standardization is not reproducible
across protocols, and the disagreement can be quantified and attributed to
specific causes.** All six stages (R1–R6) are complete: the protocol engine,
divergence analysis with ablation-based cause attribution, dataset metrics, an
interactive GUI panel, a CLI benchmark harness, and a manuscript draft populated
with real results.

**Why it's useful:** Standardization (§4) is mandatory in every cheminformatics
pipeline, but different tools/settings produce different "standard" structures
for the same input — so datasets curated differently aren't truly comparable,
and results are hard to reproduce. No existing tool measures *how much* this
happens or *why*. This is the project's genuine methodological contribution —
not a new standardizer, but a **measurement framework** for standardization
disagreement.

**Where it's used / applications:** Data curation quality control before a
QSAR/ML study, auditing whether a merged multi-source dataset has
pipeline-dependent duplicates, and — the target application — an open,
reproducible benchmark suitable for a methods publication (target: *Journal of
Cheminformatics* or a Frontiers methods/tools venue).

**Mechanism (R1, complete):**
- Standardization is modeled as a **composable set of 8 toggleable operations**
  (metal-disconnect, normalize, reionize, keep-largest-fragment, neutralize-
  charge, remove-isotopes, remove-stereo, canonicalize-tautomer), applied in a
  fixed chemically-sensible order — not one opaque "standardize" call. This is
  what makes protocols comparable and divergences attributable.
- Three presets: **Minimal** (barely clean), **ChEMBL-like** (mirrors the real
  ChEMBL pipeline — deliberately *no* tautomer step), **Aggressive** (all 8 ops).
- Each molecule's *standard identity* is captured **two ways** — canonical
  SMILES and InChIKey — because (an early, already-published-worthy finding)
  **they disagree on what counts as reproducible**: InChI silently normalizes
  tautomers internally, so a molecule can look "pipeline-dependent" under
  SMILES identity while looking perfectly reproducible under InChIKey identity.
  In an 8-molecule demonstration, SMILES flagged 5/8 molecules as
  pipeline-dependent versus 4/8 under InChIKey.
- `with_op(operation, enabled)` toggles a single operation on a protocol,
  producing a labeled variant — the primitive the next stage (R2) uses for
  **ablation-based cause attribution**: toggle one operation at a time and
  observe which flip changes the outcome, attributing each divergence to a
  specific cause rather than just flagging "these disagree."

**Mechanism (R2–R6, complete):**
- **R2 (divergence):** `analyze_molecule`/`analyze_divergence` standardize a
  molecule (or dataset) with every protocol, check agreement on both identity
  conventions, and — for labile molecules — run **ablation**: toggle each
  operation off the richest protocol one at a time; the first operation whose
  removal changes the outcome is recorded as the cause.
- **R3 (metrics):** `compute_metrics` turns a divergence run into a
  reproducibility score, a pairwise protocol-agreement matrix, and a cause
  spectrum (fraction of labile molecules each operation explains).
- **R4 (GUI):** a **Research** menu → *Reproducibility Audit…* dialog (pick
  protocols, toggle ablation) runs in the background and populates a panel with
  a protocol-agreement heatmap, a cause-spectrum bar chart, and a sortable list
  of labile molecules — all Matplotlib-rendered with export to PNG/PDF/SVG.
- **R5 (benchmark):** a Qt-free CLI (`python -m wawekit.services.reproducibility.benchmark`)
  runs the whole pipeline over a SMILES file and reports the numbers a paper
  needs. Run for real on a 40-molecule illustrative set: **70.0%
  SMILES-reproducible, 75.0% InChIKey-reproducible**, with charge handling
  (41.7% of divergences) and salt/fragment handling (33.3%) the dominant causes.
- **R6 (manuscript):** a full IMRAD draft populated with the real R5 numbers,
  ready to scale to a public ChEMBL/PubChem/DrugBank benchmark for submission.

**Workflow:**
1. **Research → Reproducibility Audit…** in the desktop app, or run the CLI:
   `python -m wawekit.services.reproducibility.benchmark molecules.smi --out results.csv`.
2. Choose which protocols to compare (Minimal/ChEMBL-like/Aggressive by
   default) and whether to attribute causes (slower).
3. Review the headline reproducibility score, the protocol-agreement heatmap,
   the cause-spectrum chart, and the list of labile molecules with their
   attributed causes.
4. See `learning/research-track-R2-to-R6-summary/`,
   `learning/research-track-R5-benchmark/` (raw results), and
   `learning/research-track-R6-manuscript/manuscript_draft.md` (the paper draft).

---

*This document is maintained alongside the codebase. When a feature changes
materially, update its section here as well as its `learning/` build notes.*
