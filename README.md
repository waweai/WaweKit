<h1 align="center">
  <img src="WaweKit.png" width="120" alt="WaweKit logo"><br>
  WaweKit
</h1>

<p align="center">
  <b>Open-source desktop cheminformatics toolkit, with a built-in auditor for
  standardization reproducibility</b><br>
  Python 3.12+ &nbsp;•&nbsp; RDKit &nbsp;•&nbsp; PySide6 &nbsp;•&nbsp;
  MIT licensed &nbsp;•&nbsp; Windows / macOS / Linux
</p>

<p align="center">
  <a href="https://github.com/waweai/WaweKit/actions">
    <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/waweai/WaweKit/ci.yml?branch=main&label=CI">
  </a>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-informational">
  <img alt="Python" src="https://img.shields.io/badge/python-3.12%2B-blue">
</p>

> **This is a mirror.** The official repository is
> **[github.com/waweai/WaweKit](https://github.com/waweai/WaweKit)** — please
> open issues and pull requests there.

---

WaweKit is a native desktop application for cheminformatics and early drug
discovery, built for academic researchers, computational chemists,
pharmaceutical scientists, and students learning the field. Load structures,
clean and standardize them, compute descriptors and fingerprints, search by
similarity or substructure, cluster, project chemical space, generate 3D
conformers, and generate shareable reports — all on background threads, with
no coding, no account, and no data leaving your machine.

Beyond the standard toolkit, WaweKit ships a capability we haven't found in
any other interactive cheminformatics tool: a **standardization reproducibility
auditor** that measures how much your choice of cleanup protocol changes a
dataset's molecular identities, attributes each disagreement to a specific
operation, and can compare your protocols directly against the real production
pipelines that ChEMBL and MolVS run. See [Research flagship](#research-flagship)
below.

## Install

WaweKit installs as a lightweight headless library by default. Add the `[gui]`
extra for the desktop application:

```bash
pip install wawekit          # library + CLI, no Qt
pip install "wawekit[gui]"   # + the desktop application
```

For development:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"      # dev = gui + standardizers + test/lint tooling
```

## Run

```bash
wawekit
# or, equivalently
python -m wawekit
```

The desktop application opens with a branded splash, then the main window. An
illustrated in-app manual is one keypress away (`Help → User Manual`, `F1`).

## Features

| | |
|---|---|
| **Load & convert** | SDF, MOL, SMILES — drag-and-drop or `File → Open`; a standalone format converter (CSV/SDF/MOL/SMILES) |
| **Standardize** | Salt stripping, charge neutralization, tautomer canonicalization, dedup — with a full change report, nothing silent |
| **Analyze** | Descriptors (MW, LogP, TPSA, HBD/HBA, RotB, rings, Lipinski), Morgan/MACCS/RDKit fingerprints, Tanimoto/Dice/Cosine similarity, Bemis–Murcko scaffolds, structural alerts (PAINS/Brenk/NIH) |
| **Explore** | 3D conformer generation (ETKDG + MMFF/UFF) with an interactive viewer, PCA/t-SNE chemical-space projection with linked table selection, Butina/K-Means clustering, SMARTS/SMILES substructure search with atom highlighting |
| **Filter** | A quick-filter box (`MW < 500`, `Sim >= 0.7`) plus an interactive property-range panel |
| **Automate** | A cancellable batch pipeline chaining standardize → descriptors → fingerprints → scaffolds → clustering → export |
| **Report** | Self-contained HTML and paginated PDF reports with embedded depictions |
| **Extend** | A plugin system discovering third-party packages via Python entry points — no fork required |
| **Research** | The standardization-reproducibility auditor — see below |

All 20 build-out modules are complete: architecture, loading, viewing,
standardization, descriptors, fingerprints, similarity, scaffolds, conformers,
chemical space, clustering, substructure search, batch processing, reporting,
settings, plugins, packaging, documentation, CI, and release preparation.
358 automated tests; CI runs lint, format and the full suite on Ubuntu,
Windows and macOS.

## Architecture

Strict layered design; dependencies point downward only:

```
gui  ->  services  ->  models  ->  core
```

| Layer | Responsibility | Requires Qt? |
|-------|----------------|:---:|
| `core` | config, logging, paths, constants | no |
| `models` | RDKit-backed domain objects | no |
| `services` | chemistry, I/O, reporting, the reproducibility auditor | no |
| `gui` | PySide6 windows, docks and dialogs | yes |

Every analysis service imports without Qt, which is what makes the headless
install possible: `wawekit.services.reproducibility` and friends are usable
as a plain library or from the command line —

```python
from rdkit import Chem
from wawekit.services.reproducibility import analyze_divergence, compute_metrics
from wawekit.services.reproducibility.protocol import DEFAULT_PROTOCOLS

records = [(name, Chem.MolFromSmiles(smi)) for name, smi in my_compounds]
metrics = compute_metrics(analyze_divergence(records, DEFAULT_PROTOCOLS))
print(f"{metrics.inchikey_reproducibility:.1%} reproducible")
```

or unattended:

```bash
python -m wawekit.services.reproducibility.benchmark compounds.smi --out results.csv
```

— without pulling in the desktop UI at all, and the GUI, CLI and library are
verified (by an automated test, not just convention) to compute identical
results for identical input.

## Development

```bash
pytest            # run the test suite
ruff check .      # lint
black .           # format
mkdocs serve      # preview docs
```

## Acknowledgements

The interactive 3D conformer viewer is powered by
[3Dmol.js](https://3dmol.csb.pitt.edu/) (BSD-3-Clause), vendored and used
offline — see `src/wawekit/resources/web/NOTICE-3Dmol.txt`. Cross-toolkit
comparison uses the openly released
[ChEMBL structure curation pipeline](https://github.com/chembl/ChEMBL_Structure_Pipeline)
and [MolVS](https://github.com/mcs07/MolVS).

## Support

If WaweKit is useful to you, consider sponsoring its development via the
"Sponsor" button on this repository (GitHub Sponsors).

## License

[MIT](LICENSE) © TheWaweAI
