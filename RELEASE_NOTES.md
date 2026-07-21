# Wawekit 0.1.0 — Release Notes

**First public release.** Wawekit is a native desktop application for
cheminformatics and early drug discovery, built with Python 3.12, RDKit and
PySide6, MIT licensed and cross-platform.

## Highlights

**Full workflow, one desktop app.** Load SDF/MOL/SMILES files; standardize
(salts, charges, tautomers, dedup); compute descriptors, fingerprints, and
Tanimoto similarity; analyze Bemis–Murcko scaffolds; generate 3D conformers
with an interactive viewer; visualize chemical space (PCA/t-SNE); cluster
(Butina/K-Means); search substructures (SMARTS/SMILES); batch-process chained
pipelines; and generate shareable HTML/PDF reports — all on background
threads with progress reporting, so nothing freezes the UI on real datasets.

**A research flagship, not just a feature list.** A standardization-
reproducibility auditor quantifies a problem the field mostly treats as
settled: different standardization protocols (and even different identity
conventions — canonical SMILES vs. InChIKey) can silently disagree on what
counts as "the same molecule." Wawekit measures this divergence directly and
attributes each disagreement to a specific normalization step via operation
ablation. On a 40-molecule illustrative benchmark: 70.0% SMILES-reproducible,
75.0% InChIKey-reproducible across three protocols, with charge handling
(41.7%) and salt/fragment handling (33.3%) the dominant causes. A full
manuscript draft is included (`learning/research-track-R6-manuscript/`).

**Extensible.** A plugin system built on Python entry points — the same
mechanism `pip` itself uses for console scripts — lets third parties add
menu actions and dock panels without touching Wawekit's source. Verified with
a real installable example plugin, not just mocks.

**Packaged and documented.** A hand-written PyInstaller spec produces a
distributable desktop bundle (see `docs/PACKAGING.md`); a MkDocs site covers
every feature's mechanism and workflow (`docs/FEATURES.md`); CI runs lint,
format, and the full test suite on Ubuntu, Windows, and macOS on every push.

## What's in this release

All 20 planned modules, built one at a time to production quality:

1. Project architecture
2. Molecule loading (SDF/MOL/SMILES, drag-and-drop)
3. Molecule viewer (2D depictions, SVG/PNG export)
4. Molecular standardization (salts, charges, tautomers, dedup)
5. Descriptors (MW, LogP, TPSA, HBD/HBA, RotB, rings, Lipinski)
6. Fingerprints (Morgan/MACCS/RDKit)
7. Similarity search (Tanimoto ranking)
8. Scaffold analysis (Bemis–Murcko, diversity grouping)
9. Conformer generation (ETKDG + MMFF/UFF, interactive 3D viewer)
10. Chemical space visualization (PCA/t-SNE)
11. Clustering (Butina + K-Means)
12. Substructure search (SMARTS/SMILES)
13. Batch processing (chained pipeline)
14. Report generation (HTML + PDF)
15. Settings (theme, log level, window/dock layout)
16. Plugin system (entry-point discovery)
17. Packaging (PyInstaller)
18. Documentation (MkDocs)
19. Testing (CI on 3 OSes)
20. Release preparation (this document)

Plus the 6-stage research track (R1–R6): protocol engine, divergence
analysis, reproducibility metrics, an interactive GUI panel, a CLI benchmark
harness, and a manuscript draft.

See `CHANGELOG.md` for the full itemized history and
[`learning/`](learning/) for build notes and, for Modules 1–15, a graphical
abstract per module.

## Known limitations

- No code signing or installer (MSI/NSIS/AppImage/dmg) — the PyInstaller
  build produces a distributable folder, not a signed installer. See
  `docs/PACKAGING.md` for what's deliberately out of scope for this release.
- Plugins run with full application privilege once activated — no
  sandboxing, permission system, or unloading. Acceptable for a v1 extension
  mechanism; a security boundary would be a substantial separate feature.
- The reproducibility benchmark (70.0%/75.0%) is measured on a 40-molecule
  illustrative set, not a large curated corpus — a real submission-quality
  benchmark would need a larger, more diverse dataset.
- No auto-update mechanism.

## Upgrading

This is the first release — no upgrade path applies yet.
