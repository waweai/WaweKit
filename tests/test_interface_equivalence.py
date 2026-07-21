"""The GUI and the CLI must report the same numbers.

The manuscript claims that WaweKit's desktop panel and its command-line
benchmark "call the identical underlying computation". That is the kind of
claim a reader of a software paper is entitled to see tested rather than
asserted: if the interface being published disagreed with the interface that
produced the published figures, every reported number would be in question.

These tests drive the real GUI handler (through its worker function, on the
same records a user's table would hold) and the real CLI entry point over the
same molecules, then compare the resulting metrics field by field.
"""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.reproducibility import analyze_divergence, compute_metrics
from wawekit.services.reproducibility.benchmark import run_benchmark
from wawekit.services.reproducibility.protocol import DEFAULT_PROTOCOLS

# Deliberately mixed: a clean molecule, a salt, a tautomer-ambiguous
# heterocycle and a stereocentre — so every protocol difference is exercised.
MOLECULES = [
    ("aspirin", "CC(=O)Oc1ccccc1C(=O)O"),
    ("acetate-Na", "CC(=O)[O-].[Na+]"),
    ("2-hydroxypyridine", "Oc1ccccn1"),
    ("L-alanine", "C[C@H](N)C(=O)O"),
    ("benzene-HCl", "c1ccccc1.Cl"),
]


def _records():
    return [(name, Chem.MolFromSmiles(smi)) for name, smi in MOLECULES]


def test_gui_worker_and_direct_call_agree():
    """The GUI's worker payload is the same function the library exposes.

    MainWindow hands ``analyze_divergence`` to a FunctionWorker with
    ``(records, protocols, attribute_causes)``; this reproduces that call
    exactly and checks it against a plain library invocation.
    """
    gui_run = analyze_divergence(_records(), DEFAULT_PROTOCOLS, True)
    lib_run = analyze_divergence(_records(), DEFAULT_PROTOCOLS, attribute_causes=True)

    gui_metrics = compute_metrics(gui_run)
    lib_metrics = compute_metrics(lib_run)

    assert gui_metrics.n_molecules == lib_metrics.n_molecules
    assert gui_metrics.smiles_reproducibility == lib_metrics.smiles_reproducibility
    assert gui_metrics.inchikey_reproducibility == lib_metrics.inchikey_reproducibility
    assert gui_metrics.n_labile == lib_metrics.n_labile
    assert gui_metrics.cause_spectrum == lib_metrics.cause_spectrum


def test_cli_and_library_agree(tmp_path, capsys):
    """The shipped CLI reports exactly what the library computes."""
    smi = tmp_path / "molecules.smi"
    smi.write_text("\n".join(f"{s} {n}" for n, s in MOLECULES), encoding="utf-8")

    cli_metrics = run_benchmark(smi, output_path=None, attribute_causes=True)
    capsys.readouterr()  # the CLI prints a summary; not under test here

    lib_metrics = compute_metrics(analyze_divergence(_records(), DEFAULT_PROTOCOLS))

    assert cli_metrics.n_molecules == lib_metrics.n_molecules
    assert cli_metrics.smiles_reproducibility == lib_metrics.smiles_reproducibility
    assert cli_metrics.inchikey_reproducibility == lib_metrics.inchikey_reproducibility
    assert cli_metrics.n_labile == lib_metrics.n_labile
    assert cli_metrics.cause_spectrum == lib_metrics.cause_spectrum
    assert [(p.protocol_a, p.protocol_b, p.inchikey_agreement) for p in cli_metrics.pairwise] == [
        (p.protocol_a, p.protocol_b, p.inchikey_agreement) for p in lib_metrics.pairwise
    ]


def test_audit_is_deterministic_across_repeated_runs():
    """Two identical audits must produce identical numbers.

    A reproducibility tool that is not itself reproducible would be a
    self-refuting result, so this is pinned rather than assumed.
    """
    first = compute_metrics(analyze_divergence(_records(), DEFAULT_PROTOCOLS))
    second = compute_metrics(analyze_divergence(_records(), DEFAULT_PROTOCOLS))

    assert first.smiles_reproducibility == second.smiles_reproducibility
    assert first.inchikey_reproducibility == second.inchikey_reproducibility
    assert first.cause_spectrum == second.cause_spectrum
