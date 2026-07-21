"""Benchmark harness: run a reproducibility audit over a file of molecules.

Qt-free and GUI-free by design, so it runs unattended over large public datasets
(ChEMBL/PubChem/ZINC subsets) from a terminal or a CI job — the R5 stage of the
research track, producing the numbers R6's manuscript reports.

Usage
-----
::

    python -m wawekit.services.reproducibility.benchmark molecules.smi --out results.csv

Input is a SMILES file (one molecule per line, optional name after whitespace —
the same format :mod:`wawekit.services.io.molecule_loader` reads). Output is a
CSV with one row per molecule (name, agreement flags, form counts, causes) plus a
summary printed to stdout.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

from rdkit import Chem

from wawekit.services.reproducibility.divergence import DivergenceRun, analyze_divergence
from wawekit.services.reproducibility.metrics import ReproducibilityMetrics, compute_metrics
from wawekit.services.reproducibility.protocol import DEFAULT_PROTOCOLS

logger = logging.getLogger(__name__)


def load_smiles_file(path: Path) -> list[tuple[str, Chem.Mol]]:
    """Read a SMILES file into ``(name, mol)`` pairs, skipping unparseable lines.

    Deliberately minimal (no error reporting UI, unlike the GUI loader) — a
    benchmark run logs and skips a bad line rather than stopping.
    """
    records: list[tuple[str, Chem.Mol]] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        mol = Chem.MolFromSmiles(parts[0])
        if mol is None:
            logger.warning("Skipping unparseable SMILES at line %d: %r", lineno, parts[0])
            continue
        name = parts[1].strip() if len(parts) > 1 else f"{path.stem}_{lineno}"
        records.append((name, mol))
    return records


def write_results_csv(run: DivergenceRun, path: Path) -> None:
    """Write one row per molecule: agreement flags, form counts, causes."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "name",
                "smiles_agree",
                "inchikey_agree",
                "n_distinct_smiles",
                "n_distinct_inchikeys",
                "n_failed_protocols",
                "causes",
            ]
        )
        for result in run.results:
            writer.writerow(
                [
                    result.name,
                    result.smiles_agree,
                    result.inchikey_agree,
                    result.n_distinct_smiles,
                    result.n_distinct_inchikeys,
                    result.n_failed,
                    ";".join(op.value for op in result.causes),
                ]
            )


def print_summary(metrics: ReproducibilityMetrics) -> None:
    """Print the headline numbers a paper would report."""
    print(f"Molecules analyzed:       {metrics.n_molecules}")
    print(f"SMILES reproducibility:   {metrics.smiles_reproducibility:.1%}")
    print(f"InChIKey reproducibility: {metrics.inchikey_reproducibility:.1%}")
    print(f"Labile molecules:         {metrics.n_labile}")
    if metrics.n_with_failures:
        print(f"Molecules with failures:  {metrics.n_with_failures}")
    print()
    print("Pairwise agreement (InChIKey):")
    for pair in metrics.pairwise:
        print(f"  {pair.protocol_a:15} vs {pair.protocol_b:15} {pair.inchikey_agreement:.1%}")
    if metrics.cause_spectrum:
        print()
        print("Divergence cause spectrum (fraction of labile molecules):")
        for op, frac in sorted(metrics.cause_spectrum.items(), key=lambda kv: -kv[1]):
            if frac > 0:
                print(f"  {op.value:22} {frac:.1%}")


def run_benchmark(
    input_path: Path,
    output_path: Path | None = None,
    attribute_causes: bool = True,
) -> ReproducibilityMetrics:
    """Load, audit, and report — the whole benchmark in one call.

    Parameters
    ----------
    input_path:
        SMILES file to audit.
    output_path:
        Optional CSV path for per-molecule results.
    attribute_causes:
        Whether to run ablation-based cause attribution (slower).

    Returns
    -------
    ReproducibilityMetrics
        The dataset-level summary (also printed to stdout).

    """
    records = load_smiles_file(input_path)
    print(f"Loaded {len(records)} molecule(s) from {input_path}")

    started = time.perf_counter()
    run = analyze_divergence(records, DEFAULT_PROTOCOLS, attribute_causes=attribute_causes)
    elapsed = time.perf_counter() - started
    print(f"Audited in {elapsed:.1f}s ({len(records) / max(elapsed, 1e-9):.0f} molecules/s)\n")

    metrics = compute_metrics(run)
    print_summary(metrics)

    if output_path is not None:
        write_results_csv(run, output_path)
        print(f"\nPer-molecule results written to {output_path}")

    return metrics


def main(argv: list[str] | None = None) -> int:
    """CLI entry point (also reachable via ``python -m ...reproducibility.benchmark``)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", type=Path, help="SMILES file to audit")
    parser.add_argument("--out", type=Path, default=None, help="CSV path for per-molecule results")
    parser.add_argument(
        "--no-causes", action="store_true", help="Skip ablation-based cause attribution (faster)"
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(f"error: {args.input} does not exist", file=sys.stderr)
        return 1

    run_benchmark(args.input, args.out, attribute_causes=not args.no_causes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
