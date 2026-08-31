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

Requirements: **Python 3.12 or newer**, 64-bit, on Windows / macOS / Linux, and
roughly 2 GB of disk space once RDKit and Qt are installed. No account, no
internet connection at run time, no data leaves your machine.

### Install with pip (any OS)

```bash
pip install "wawekit[gui] @ git+https://github.com/waweai/WaweKit.git"
```

That is the desktop application. For the headless library and CLI only — the
analysis layers import without Qt, so this skips the ~150 MB GUI stack:

```bash
pip install "wawekit @ git+https://github.com/waweai/WaweKit.git"
```

> WaweKit is not on PyPI yet. Once it is published, these become the shorter
> `pip install "wawekit[gui]"` / `pip install wawekit`.

Optional extras, combinable (`"wawekit[gui,standardizers]"`):

| Extra | Adds |
|---|---|
| `gui` | PySide6 + matplotlib — the desktop application |
| `standardizers` | ChEMBL structure pipeline + MolVS, so the auditor can compare against those production pipelines |
| `science` | plotly + openpyxl for the richer export formats |
| `dev` | everything above plus pytest, ruff, black, mkdocs, pyinstaller |

Installing into a virtual environment is recommended, so WaweKit's RDKit and Qt
versions cannot collide with another project's:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install "wawekit[gui] @ git+https://github.com/waweai/WaweKit.git"
```

### Install from source

```bash
git clone https://github.com/waweai/WaweKit.git
cd WaweKit
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"      # dev = gui + standardizers + test/lint tooling
pytest                       # optional: confirm the suite passes on your machine
```

### Desktop builds (no Python needed)

For users who should never have to touch a Python environment, WaweKit builds
into a self-contained desktop application on all three platforms:

| Platform | Artifact |
|---|---|
| Windows | `WaweKitSetup-x.y.z.exe` — an installer with a **Create a desktop icon** box, a per-user install needing no administrator rights, and a clean Add/Remove Programs entry |
| macOS | a `.dmg`; open it and drag WaweKit into Applications |
| Linux | a portable `.tar.gz` of the frozen application folder |

No release has been published yet, so for now these have to be built — one
command per platform, described in [docs/PACKAGING.md](docs/PACKAGING.md).
Because the executables are not code-signed yet, Windows SmartScreen and macOS
Gatekeeper will warn on first run.

## Run

```bash
wawekit
# or, equivalently
python -m wawekit
```

The desktop application opens with a branded splash, then the main window. An
illustrated in-app manual is one keypress away (`Help → User Manual`, `F1`).

### Desktop icon

The first launch after installing puts a **WaweKit icon on your desktop** and
registers the app with the Start Menu (Windows) or applications menu (Linux),
so afterwards you can start it by double-clicking rather than by typing a
command. It happens once: delete the icon and it stays deleted.

To create or remove it yourself at any time:

```bash
wawekit-shortcut              # desktop icon + menu entry
wawekit-shortcut --remove     # take them away again
```

`Help → Create Desktop Shortcut` does the same thing from inside the app. To
suppress the automatic first-run icon (shared or headless machines), set
`create_desktop_shortcut = false` in `settings.toml` before the first run.
Users who install the packaged Windows build get the icon from the installer's
own *Create a desktop icon* checkbox instead — see
[docs/PACKAGING.md](docs/PACKAGING.md).

## Quick start

The repository ships small demo sets in [`samples/`](samples), so there is
something to work with in the first minute:

1. **Load** — drag `samples/demo_set.smi` onto the window, or `File → Open`.
   The table fills; click any row to see the structure.
2. **Clean** — `Chemistry → Standardize`. Pick the operations you want; the
   result is a change report, so you can see exactly what was altered rather
   than trusting a silent rewrite.
3. **Describe** — `Chemistry → Compute Descriptors` adds MW, LogP, TPSA,
   HBD/HBA and the rest as sortable columns. Type `MW < 500` in the
   quick-filter box to narrow the table.
4. **Explore** — `Chemistry → Similarity Search` ranks by Tanimoto against a
   reference; `Chemistry → Chemical Space` projects the set with PCA/t-SNE and
   stays linked to the table selection.
5. **Report** — `File → Generate Report` writes a self-contained HTML or PDF
   with embedded depictions.

Everything long-running happens on background threads and is cancellable, so
the window never freezes. Press `F1` at any point for the full illustrated
manual, and see [docs/FEATURES.md](docs/FEATURES.md) for the feature-by-feature
reference.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `wawekit: command not found` | The script directory is not on `PATH`. Use `python -m wawekit`, or activate the virtual environment you installed into. |
| *"The WaweKit desktop application requires the optional GUI dependencies"* | You installed the headless library. Re-install with the `[gui]` extra. |
| No desktop icon appeared | Run `wawekit-shortcut`, or use `Help → Create Desktop Shortcut`. It is only ever created automatically once. |
| Linux: *"could not load the Qt platform plugin xcb"* | Install the system Qt libraries, e.g. `sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libegl1`. |
| Windows SmartScreen blocks the installer | The build is not code-signed yet — *More info → Run anyway*. |
| Something misbehaves and you want detail | Raise the log level in `File → Settings` to `DEBUG`. The log file lives under the OS app-data directory (`%APPDATA%\TheWaweAI\Wawekit\logs` on Windows) and its full path is written to the console at startup. |

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

## Research flagship

Structure standardization is mandatory in every cheminformatics pipeline, but
the *protocol* used to perform it — which operations, in what order — varies
across tools and configurations, and is rarely reported precisely enough to
reproduce. WaweKit treats standardization reproducibility as a measurable,
first-class property of a dataset rather than an implicit assumption.

`Research → Reproducibility Audit` (`Ctrl+Shift+R`) runs two or more
standardizers over your loaded dataset and reports:

- **Whether they agree**, under two identity conventions (canonical SMILES and
  InChIKey) that can genuinely disagree with each other.
- **Why they don't**, via systematic operation ablation — attributing each
  disagreement to the specific normalization step responsible, not just
  flagging that a disagreement exists.
- **Cross-toolkit comparison.** Standardizers aren't limited to protocols
  composed from RDKit operations — WaweKit ships adapters for **ChEMBL's own
  production curation pipeline** and for **MolVS**, so you can ask directly
  "does my pipeline agree with the one this database runs?"

On a seeded random sample of 4,972 ChEMBL structures, three RDKit-composed
protocols agreed on only **54.1%** of molecules under canonical-SMILES identity
and **57.7%** under InChIKey identity. Comparing against the real production
pipelines found that WaweKit's composed approximation of the ChEMBL pipeline
reproduces the actual pipeline on **99.8%** of structures — and, more
surprisingly, that **two configurations of one standardizer (MolVS) agreed
with each other on only 56.0% of structures, while two independently
developed standardizers agreed on 77.2%** — configuration choice within a
single tool spans a wider range of outcomes than the choice between tools.

A companion downstream-impact study, applying the same audit to 27,152 real
bioactivity measurements across four drug targets, found that aggressive
standardization can silently delete up to 9.5% of a dataset by merging
compounds and fuse activities differing by a thousandfold into single
training labels — while leaving the aggregate metrics normally used to
validate a pipeline statistically unchanged. In short: an unmoved model score
is not evidence that a standardization change was safe.

Two manuscript drafts describing the method and the software are included
under [`learning/`](learning/) in the full development repository, along with
every script, seed and raw result needed to regenerate the figures above from
scratch.

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

## Documentation

- [`docs/FEATURES.md`](docs/FEATURES.md) — what every feature is, why it's
  useful, and how it works internally.
- [`docs/PACKAGING.md`](docs/PACKAGING.md) — building a distributable desktop
  bundle with PyInstaller.
- An illustrated manual ships inside the app itself (`Help → User Manual`).

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
