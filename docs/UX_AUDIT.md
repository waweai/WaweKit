# Usability audit — 15 August 2026

Fifteen findings from driving the running application through a real session:
load → select → standardize → descriptors → fingerprints → scaffolds → PCA
projection → clustering.

**Method.** The PySide6 app driven programmatically at 1500×950 in the dark
theme, loading `samples/demo_set.smi` (9 molecules, 1 deliberate parse
failure). Every count and value below was read out of the live widgets, not
inferred from the source.

Findings are ranked by how much damage each one does to a user's trust in the
numbers on screen. Nothing here is fixed yet — this is the to-do list.

---

## Trust breakers

### 1. Computing descriptors silently deletes molecules from the table

Load nine molecules, press **Compute Descriptors**, and two of them disappear.
Nothing is announced: the status bar reports a clean run, the counter still
says nine, and the rows are simply gone.

The cause is the Property Filters panel. When descriptors arrive it
auto-populates each range with the dataset's own min and max — but the spin
boxes are set to two decimals, so the stored maximum is *rounded down* below
the real value, and the molecule that defines that maximum then fails its own
filter.

```
rows loaded          9
rows the user sees   7
missing              anthracene, procainamide

anthracene    LogP = 3.993000000000002   filter max = 3.99   -> hidden
procainamide  MW   = 235.33100000000002  filter max = 235.33 -> hidden
```

- **Where:** `gui/widgets/property_filter_panel.py:84-86` sets
  `setDecimals(2)`; `:154-157` writes the un-rounded min/max into those boxes;
  `:168` emits the filter immediately.
- **Fix:** floor the minimum and ceil the maximum to the displayed precision
  before setting them — and better, do not apply a filter the user never
  touched. Populate the bounds, leave the channel inactive until a control
  moves.

### 2. The molecule counter reports a number that is no longer on screen

With seven of nine rows showing, the label under the table still reads
`9 molecule(s)`. It only switches to the honest `7 of 9 shown` form for the
quick-filter, scaffold and substructure channels — the property-range channel
was never added to that check, so the one filter that applies itself
automatically is also the one that never announces itself.

- **Where:** `gui/widgets/molecule_table.py:757-763` — `narrowed` tests the
  scaffold and substructure filters only.
- **Fix:** include every filter channel in that test, and add a dismissible
  "Filters active — clear" chip above the table. A hidden row a chemist cannot
  account for is a reproducibility problem, not a cosmetic one.

### 3. There is no way to save the table you just built

Load, standardize, compute descriptors and fingerprints, cluster, assign
scaffolds — then try to keep it. The File menu offers Open, Convert, Generate
Report, Settings and Quit. Export exists only *inside* the batch pipeline and
the standalone converter, neither of which exports the working dataset with its
computed columns. The right-click menu copies SMILES and names to the
clipboard; that is the whole export story.

- **Fix:** `File → Export Table…` (CSV / SDF / XLSX) with a scope choice of all
  rows / filtered rows / selected rows, plus `Ctrl+S`. Every computed column
  the user is looking at should be in the file.

## Workflow blockers

### 4. Computing descriptors looks like it did nothing

The eight new columns land off the right edge of the table and the view does
not move. The user's only evidence that anything happened is a status-bar line
that clears itself.

```
columns after descriptors  21   (#, Structure, Name, SMILES, Formula, Heavy atoms,
                                 MW, LogP, TPSA, HBD, HBA, RotB, Rings, Lipinski,
                                 Fingerprint, Similarity, Scaffold, Cluster,
                                 Substructure, Alerts, Source)
total column width         2188 px
table viewport width        516 px   (two docks take the rest)
```

- **Fix:** scroll the first new column into view and flash its header; freeze
  `#`/`Name` while the rest scrolls; give SMILES an elided width; add a column
  chooser. Columns for analyses that were never run (Similarity, Cluster,
  Substructure) should stay hidden until they hold something.

### 5. Only the batch pipeline can be cancelled

The Cancel button next to the progress bar is revealed for batch runs alone
(`gui/main_window.py:603-607`). Descriptors, fingerprints, conformer
generation, t-SNE and the reproducibility audit — the operations that actually
take minutes on a real library — start and cannot be stopped.

- **Fix:** every worker that can run longer than a second gets the same cancel
  affordance, and the progress text should name what is running and how far
  along it is ("Fingerprints — 12,400 / 100,000").

### 6. Every operation runs on the whole dataset, never on the selection

The table supports multi-row selection, and each analysis takes
`list(model.records)` regardless. "Generate conformers for these six hits" —
the most common way this work actually gets done — has no path through the UI
short of deleting everything else.

- **Fix:** a scope control in each dialog — All molecules / Filtered /
  Selected (n) — defaulting to Selected when a selection exists.

### 7. "Remove Selected" is instant, silent and permanent

The right-click menu deletes rows with no confirmation
(`gui/widgets/molecule_table.py:819-822`), and the application has no undo
anywhere. Combined with finding 3, a mis-click after an hour's work costs the
hour.

- **Fix:** `Ctrl+Z` for row removal, or a status-bar "Removed 5 molecules —
  Undo" for a few seconds. Undo beats a confirmation dialog.

### 8. Option dialogs are modal, so you cannot look at your data while choosing

Similarity Search asks which molecule to use as the query while covering the
table that would tell you. The same applies to clustering cutoffs, projection
settings and conformer counts — all decisions made *by looking at the set*.

- **Fix:** make the analysis dialogs non-modal, or move their controls into the
  dock panel that shows the result, so parameters and output live together and
  re-running is one click.

## Polish and defaults

### 9. The chemical-space map opens as a letterbox slit

The flagship visual appears in a bottom dock roughly 110 px tall, so the points
render in a horizontal band with the axes crushed together; matplotlib says so
during the run (`UserWarning: Tight layout not applied`). No `resizeDocks` call
ever sets a starting height (`gui/main_window.py:323`).

- **Fix:** give the bottom dock ~35 % of the window on first reveal, enforce a
  minimum height, and add a "pop out to window" affordance.

### 10. Clustering reports a useless result without saying so

With the default Butina cutoff of 0.35 the demo set produced **9 clusters of
1** — every molecule a singleton — reported as a success: "Clustered 9
molecule(s) into 9 cluster(s) (largest 1)".

- **Fix:** detect the degenerate outcomes (all singletons, or one cluster
  holding everything) and say what to do: "Every molecule formed its own
  cluster — try a cutoff above 0.5." Keep the cutoff control in the results
  panel so it can be re-run without reopening a dialog. In the Batch dialog the
  Butina cutoff box stays enabled even when the Cluster step is unchecked —
  grey it out.

### 11. The first screen is three panels of placeholder text

On launch the user meets "Welcome to Wawekit", "Select a molecule in the
table…" and "Load molecules and compute descriptors to filter by property." —
three greyed messages, no button among them. The Property Filters dock holds
about 40 % of the window width to show one of them, and there is no
recent-files list and no way to open the shipped `samples/` data from inside
the app.

- **Fix:** one empty state, centred in the table area, with real buttons —
  **Open molecules…**, **Load a sample set** — and a recent-files list.
  Collapse the filter dock until there are descriptors to filter.

### 12. The toolbar hides its own features behind a chevron

At 1500 px wide — wider than the app's own 1280 default — the toolbar already
overflows: Clustering, Substructure, Batch, Report and Theme fold into the `»`
menu. The full text labels on the visible buttons are what eat the room.

- **Fix:** icons-only with tooltips beyond the first few actions, or grouped
  dropdowns (Analyze ▾ / Explore ▾), and let the user choose what sits there.

### 13. Structural alerts appear as raw rule names in warning red

Selecting aspirin shows `⚠ Alerts: phenol_ester` in red. It does not say which
catalogue the rule came from (PAINS? Brenk? NIH?), what it implies, or which
atoms matched — and flagging aspirin in red with no context reads as "this
molecule is bad".

- **Fix:** show catalogue · rule · plain-language meaning on hover, highlight
  the matching atoms in the depiction, and drop the alarm colour to an
  informational tone. An alert is a flag for review, not a verdict.

### 14. Selection and the structure preview drift apart

After a clustering run the Structure panel falls back to "Select a molecule in
the table to see its structure here." while a cell in the table is still
painted as current — a selected row and an empty preview at the same time.
Selecting a row also paints the depiction cell with the selection colour, which
puts a mid-blue wash behind a black-and-red line drawing.

- **Fix:** re-emit the current record after any model reset, and exclude the
  Structure column from the selection wash — a thin border is enough.

### 15. Settings holds three options; the ones a chemist wants are not there

Theme, log level and "remember window layout" are the whole dialog. Missing:
default fingerprint and radius, decimal places for descriptor columns,
depiction size, default export folder, whether alerts run automatically — and
the `create_desktop_shortcut` preference that exists in the config file with no
UI. There is also no `Ctrl+F` to jump to the filter box.

- **Fix:** group Settings into Appearance / Chemistry defaults / Files &
  export / Advanced, and surface the defaults that change what the numbers
  mean.

---

## If only five get fixed

1. **The rounding bug in the property filter** (1) — molecules vanishing from a
   dataset is the one class of defect a cheminformatics tool cannot ship with.
2. **Tell the truth in the row counter** (2) — one line of code, and a silent
   failure becomes a visible state.
3. **File → Export Table** (3) — without it every analysis in the app is a dead
   end.
4. **Reveal new columns after a computation** (4) — the app currently hides its
   own best work.
5. **Cancel on every long operation** (5) — the difference between a tool you
   trust with 100,000 molecules and one you do not.
