"""Tests for the benchmark harness (CLI-facing, Qt-free)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.services.reproducibility.benchmark import (
    load_smiles_file,
    main,
    run_benchmark,
    write_results_csv,
)
from wawekit.services.reproducibility.divergence import analyze_divergence
from wawekit.services.reproducibility.protocol import DEFAULT_PROTOCOLS


def _write_smi(tmp_path, lines: list[str]):
    path = tmp_path / "molecules.smi"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_load_smiles_file_parses_names_and_skips_bad_lines(tmp_path):
    path = _write_smi(
        tmp_path,
        ["# comment", "c1ccccc1 benzene", "not-a-smiles bad", "CCO ethanol", ""],
    )
    records = load_smiles_file(path)
    names = [n for n, _ in records]
    assert names == ["benzene", "ethanol"]  # bad line skipped, comment ignored


def test_load_smiles_file_generates_a_name_when_absent(tmp_path):
    path = _write_smi(tmp_path, ["CCO"])
    records = load_smiles_file(path)
    assert records[0][0] == "molecules_1"


def test_write_results_csv_has_one_row_per_molecule(tmp_path):
    records = [("benzene", Chem.MolFromSmiles("c1ccccc1"))]
    run = analyze_divergence(records, DEFAULT_PROTOCOLS)
    out = tmp_path / "results.csv"
    write_results_csv(run, out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("name,smiles_agree")
    assert len(lines) == 2  # header + 1 molecule


def test_run_benchmark_end_to_end(tmp_path, capsys):
    smi = _write_smi(tmp_path, ["c1ccccc1 benzene", "c1ccccc1.Cl salt", "Oc1ccccn1 pyridone"])
    out_csv = tmp_path / "out.csv"
    metrics = run_benchmark(smi, out_csv, attribute_causes=True)

    assert metrics.n_molecules == 3
    assert out_csv.exists()
    captured = capsys.readouterr()
    assert "reproducibility" in captured.out.lower()


def test_cli_main_returns_zero_on_success(tmp_path):
    smi = _write_smi(tmp_path, ["CCO ethanol", "c1ccccc1 benzene"])
    out_csv = tmp_path / "out.csv"
    code = main([str(smi), "--out", str(out_csv)])
    assert code == 0
    assert out_csv.exists()


def test_cli_main_returns_nonzero_for_missing_file(tmp_path):
    code = main([str(tmp_path / "does_not_exist.smi")])
    assert code == 1


def test_cli_no_causes_flag_skips_ablation(tmp_path, capsys):
    smi = _write_smi(tmp_path, ["c1ccccc1.Cl salt"])
    code = main([str(smi), "--no-causes"])
    assert code == 0
    # With causes skipped, the spectrum section should not print operation names.
    captured = capsys.readouterr()
    assert "cause spectrum" not in captured.out.lower() or "0.0%" in captured.out
