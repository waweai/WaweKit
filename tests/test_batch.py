"""Tests for the batch pipeline runner (pure services, no Qt)."""

from __future__ import annotations

import threading

from rdkit import Chem

from wawekit.models.fingerprints import FingerprintOptions
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.batch import BatchConfig, ExportFormat, run_batch
from wawekit.services.chemistry.clustering import ClusterOptions
from wawekit.services.chemistry.standardizer import StandardizationOptions


def _records(*smiles_names: tuple[str, str]) -> list[MoleculeRecord]:
    return [MoleculeRecord(mol=Chem.MolFromSmiles(smi), name=name) for smi, name in smiles_names]


def _demo() -> list[MoleculeRecord]:
    return _records(
        ("CCO", "ethanol"),
        ("c1ccccc1", "benzene"),
        ("CC(=O)Oc1ccccc1C(=O)O", "aspirin"),
        ("c1ccncc1", "pyridine"),
    )


def test_runs_all_enabled_steps_and_caches_results():
    records = _demo()
    config = BatchConfig(
        descriptors=True,
        fingerprints=FingerprintOptions(),
        scaffolds=True,
        cluster=ClusterOptions(cutoff=0.5),
    )
    result = run_batch(records, config)

    assert not result.cancelled
    assert len(result.summaries) == 4  # descriptors, fingerprints, scaffolds, cluster
    assert all(r.descriptors is not None for r in result.records)
    assert all(r.fingerprint is not None for r in result.records)
    assert all(r.scaffold is not None for r in result.records)
    assert all(r.cluster is not None for r in result.records)


def test_standardize_step_replaces_the_records():
    records = _records(("c1ccccc1.[Na+].[Cl-]", "benzene-salt"), ("CCO", "ethanol"))
    config = BatchConfig(standardize=StandardizationOptions())
    result = run_batch(records, config)
    # Standardization returns new records (salt stripped), not the inputs.
    assert result.records[0] is not records[0]
    assert "." not in result.records[0].smiles


def test_export_step_writes_a_file(tmp_path):
    path = tmp_path / "results.csv"
    result = run_batch(
        _demo(),
        BatchConfig(descriptors=True, export_path=path, export_format=ExportFormat.CSV),
    )
    assert path.exists()
    assert result.export_path == path
    assert result.exported == 4


def test_export_sdf_format(tmp_path):
    path = tmp_path / "results.sdf"
    run_batch(_demo(), BatchConfig(export_path=path, export_format=ExportFormat.SDF))
    assert path.exists()
    assert path.read_text(encoding="utf-8").count("$$$$") == 4


def test_empty_config_does_nothing():
    records = _demo()
    result = run_batch(records, BatchConfig())
    assert result.summaries == []
    assert result.records == records


def test_cancellation_stops_the_pipeline():
    # A cancel event already set means the run stops at the very first check.
    event = threading.Event()
    event.set()
    result = run_batch(_demo(), BatchConfig(descriptors=True, scaffolds=True), cancel_event=event)
    assert result.cancelled
    # Nothing ran: descriptors were never computed.
    assert all(r.descriptors is None for r in result.records)


def test_cancellation_mid_pipeline_keeps_earlier_steps():
    # Cancel only after the first step's progress fires.
    event = threading.Event()
    records = _demo()
    seen = {"ticks": 0}

    def progress(done: int, total: int) -> None:
        seen["ticks"] += 1
        if seen["ticks"] >= 1:
            event.set()  # cancel after the first tick

    result = run_batch(
        records,
        BatchConfig(descriptors=True, scaffolds=True),
        progress=progress,
        cancel_event=event,
    )
    assert result.cancelled


def test_progress_is_cumulative_and_reaches_total():
    calls: list[tuple[int, int]] = []
    run_batch(
        _demo(),
        BatchConfig(descriptors=True, scaffolds=True),
        progress=lambda d, t: calls.append((d, t)),
    )
    # Monotonic, non-decreasing, ending at the total.
    dones = [d for d, _ in calls]
    assert dones == sorted(dones)
    assert calls[-1][0] == calls[-1][1]
