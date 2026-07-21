"""Tests for report generation (HTML + PDF, pure services, no Qt)."""

from __future__ import annotations

from rdkit import Chem

from wawekit.models.molecule import MoleculeRecord
from wawekit.services.chemistry.clustering import ClusterOptions, cluster_molecules
from wawekit.services.chemistry.descriptors import compute_descriptors
from wawekit.services.reporting import (
    ReportConfig,
    ReportFormat,
    build_summary,
    generate_report,
)


def _records() -> list[MoleculeRecord]:
    return [
        MoleculeRecord(mol=Chem.MolFromSmiles(smi), name=name)
        for smi, name in (
            ("CC(=O)Oc1ccccc1C(=O)O", "aspirin"),
            ("CCO", "ethanol"),
            ("c1ccncc1", "pyridine"),
            ("CC(C)Cc1ccc(cc1)C(C)C(=O)O", "ibuprofen"),
        )
    ]


def test_summary_reports_descriptor_stats_when_computed():
    records = _records()
    compute_descriptors(records)
    summary = build_summary(records, "Test")

    assert summary.n_molecules == 4
    assert summary.descriptor_stats  # non-empty
    mw = next(s for s in summary.descriptor_stats if s.spec.key == "MW")
    assert mw.minimum <= mw.mean <= mw.maximum
    assert summary.lipinski_pass is not None


def test_summary_is_silent_about_uncomputed_values():
    summary = build_summary(_records(), "Test")
    assert summary.descriptor_stats == []
    assert summary.lipinski_pass is None
    assert summary.n_clusters is None
    assert summary.n_scaffolds is None


def test_summary_counts_clusters():
    records = _records()
    cluster_molecules(records, ClusterOptions(cutoff=0.6))
    summary = build_summary(records, "Test")
    assert summary.n_clusters is not None and summary.n_clusters >= 1


def test_generate_html_report_writes_a_self_contained_file(tmp_path):
    records = _records()
    compute_descriptors(records)
    config = ReportConfig(
        title="My Set", output_path=tmp_path / "rep", formats=(ReportFormat.HTML,)
    )
    result = generate_report(records, config)

    html_path = tmp_path / "rep.html"
    assert result.paths == [html_path]
    text = html_path.read_text(encoding="utf-8")
    assert "<html" in text and "My Set" in text
    assert "<svg" in text  # depictions embedded inline
    assert "aspirin" in text


def test_generate_pdf_report_writes_a_pdf(tmp_path):
    config = ReportConfig(output_path=tmp_path / "rep", formats=(ReportFormat.PDF,))
    result = generate_report(_records(), config)
    pdf_path = tmp_path / "rep.pdf"
    assert result.paths == [pdf_path]
    assert pdf_path.read_bytes()[:5] == b"%PDF-"  # PDF magic


def test_generate_both_formats(tmp_path):
    config = ReportConfig(
        output_path=tmp_path / "rep", formats=(ReportFormat.HTML, ReportFormat.PDF)
    )
    result = generate_report(_records(), config)
    assert {p.suffix for p in result.paths} == {".html", ".pdf"}
    assert all(p.exists() for p in result.paths)


def test_max_molecules_truncates_the_grid_but_not_the_summary(tmp_path):
    records = _records()
    config = ReportConfig(
        output_path=tmp_path / "rep", formats=(ReportFormat.HTML,), max_molecules=2
    )
    generate_report(records, config)
    text = (tmp_path / "rep.html").read_text(encoding="utf-8")
    assert "2 more molecule(s) not shown" in text
    # The summary still counts all four.
    assert "<b>4</b>" in text


def test_progress_callback_reaches_total(tmp_path):
    calls: list[tuple[int, int]] = []
    generate_report(
        _records(),
        ReportConfig(output_path=tmp_path / "rep", formats=(ReportFormat.HTML,)),
        progress=lambda d, t: calls.append((d, t)),
    )
    assert calls[-1][0] == calls[-1][1]
