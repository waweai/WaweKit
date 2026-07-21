"""PDF report writer, built with ReportLab.

Produces a paginated, print-ready ``.pdf``: a title, the descriptor-summary
table, then a grid of molecule cards. Depictions are rasterized to PNG by
RDKit's Cairo backend (:func:`~wawekit.services.rendering.mol_renderer.render_png`),
so — like the HTML writer — this stays entirely off Qt and runs in the worker.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback
from wawekit.services.rendering.mol_renderer import render_png
from wawekit.services.reporting.report import ReportConfig, ReportSummary

logger = logging.getLogger(__name__)

#: Molecule cards per row in the grid.
_COLUMNS = 3

#: Depiction pixel size (rendered) and its placed size on the page.
_PX = (240, 170)
_CARD_IMG = (4.6 * cm, 3.25 * cm)


def _styles() -> dict[str, ParagraphStyle]:
    """Return the paragraph styles the report uses."""
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("wk-title", parent=base["Title"], fontSize=20, spaceAfter=2),
        "meta": ParagraphStyle("wk-meta", parent=base["Normal"], fontSize=8, textColor=colors.grey),
        "h2": ParagraphStyle(
            "wk-h2", parent=base["Heading2"], fontSize=11, textColor=colors.HexColor("#374151")
        ),
        "name": ParagraphStyle("wk-name", parent=base["Normal"], fontSize=8, alignment=TA_CENTER),
        "props": ParagraphStyle(
            "wk-props",
            parent=base["Normal"],
            fontSize=7,
            textColor=colors.HexColor("#4b5563"),
            alignment=TA_CENTER,
            leading=9,
        ),
    }


def _summary_flowables(summary: ReportSummary, styles: dict[str, ParagraphStyle]) -> list:
    """Build the title, metadata, headline facts and descriptor-stats table."""
    flow: list = [
        Paragraph(summary.title, styles["title"]),
        Paragraph(f"Generated {summary.generated} · Wawekit {summary.version}", styles["meta"]),
        Spacer(1, 0.4 * cm),
    ]

    facts = [f"Molecules: {summary.n_molecules}"]
    if summary.lipinski_pass is not None:
        facts.append(f"Pass Lipinski: {summary.lipinski_pass}")
    if summary.n_clusters is not None:
        facts.append(f"Clusters: {summary.n_clusters}")
    if summary.n_scaffolds is not None:
        facts.append(f"Scaffolds: {summary.n_scaffolds}")
    flow.append(Paragraph("  ·  ".join(facts), styles["meta"]))
    flow.append(Spacer(1, 0.3 * cm))

    if summary.descriptor_stats:
        flow.append(Paragraph("Descriptor summary", styles["h2"]))
        data = [["Descriptor", "Min", "Mean", "Max"]]
        data += [
            [s.spec.label, f"{s.minimum:.2f}", f"{s.mean:.2f}", f"{s.maximum:.2f}"]
            for s in summary.descriptor_stats
        ]
        table = Table(data, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ]
            )
        )
        flow.append(table)
    flow.append(Spacer(1, 0.4 * cm))
    flow.append(Paragraph("Molecules", styles["h2"]))
    return flow


def _card(
    record: MoleculeRecord, include_depiction: bool, styles: dict[str, ParagraphStyle]
) -> list:
    """Build one molecule card's flowables (image + name + props)."""
    cell: list = []
    if include_depiction:
        try:
            png = render_png(record.mol, _PX[0], _PX[1], dark=False)
            cell.append(Image(io.BytesIO(png), width=_CARD_IMG[0], height=_CARD_IMG[1]))
        except Exception:  # noqa: BLE001 — a bad depiction must not abort the report
            logger.exception("Failed to depict %s for the PDF report", record.name)

    cell.append(Paragraph(f"<b>{record.name}</b><br/>{record.formula}", styles["name"]))
    prop_bits: list[str] = []
    if record.descriptors is not None:
        for spec in DESCRIPTOR_SPECS[:6]:  # keep the card compact
            prop_bits.append(f"{spec.label} {spec.fmt.format(spec.getter(record.descriptors))}")
    if record.cluster is not None:
        prop_bits.append(f"Cluster {record.cluster.cluster_id}")
    if prop_bits:
        cell.append(Paragraph(" · ".join(prop_bits), styles["props"]))
    return cell


def write_pdf(
    records: list[MoleculeRecord],
    summary: ReportSummary,
    config: ReportConfig,
    truncated: int,
    path: Path,
    progress: ProgressCallback,
) -> None:
    """Write a paginated PDF report to ``path``."""
    styles = _styles()
    flow = _summary_flowables(summary, styles)

    cells: list = []
    for index, record in enumerate(records):
        cells.append(_card(record, config.include_depictions, styles))
        progress(index + 1, len(records))

    # Pad the last row so the grid table is rectangular, then chunk into rows.
    while len(cells) % _COLUMNS != 0:
        cells.append("")
    rows = [cells[i : i + _COLUMNS] for i in range(0, len(cells), _COLUMNS)]
    if rows:
        grid = Table(rows, colWidths=[5.6 * cm] * _COLUMNS, hAlign="LEFT")
        grid.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        flow.append(grid)

    if truncated > 0:
        flow.append(Spacer(1, 0.3 * cm))
        flow.append(
            Paragraph(
                f"… and {truncated} more molecule(s) not shown "
                f"(summary covers all {summary.n_molecules}).",
                styles["meta"],
            )
        )

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        title=summary.title,
        author=f"Wawekit {summary.version}",
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )
    doc.build(flow)
    logger.info("Wrote PDF report to %s", path)
