"""Self-contained HTML report writer.

Produces a single ``.html`` file that opens in any browser and prints to PDF.
Molecule depictions are embedded as **inline SVG** — crisp at any zoom, no
external files, no rasterization. Styling is inline CSS with a light palette
(reports are for printing and sharing), plus a ``@media print`` block so page
breaks fall between molecule cards.
"""

from __future__ import annotations

import html
import logging
from pathlib import Path

from wawekit.models.descriptors import DESCRIPTOR_SPECS
from wawekit.models.molecule import MoleculeRecord
from wawekit.services.io.molecule_loader import ProgressCallback
from wawekit.services.rendering.mol_renderer import render_svg
from wawekit.services.reporting.report import ReportConfig, ReportSummary

logger = logging.getLogger(__name__)

_CSS = """
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 32px; background: #ffffff; color: #1e1f22;
         font-family: "Segoe UI", system-ui, -apple-system, sans-serif; }
  h1 { font-size: 24px; margin: 0 0 4px; }
  .meta { color: #6b7280; font-size: 13px; margin-bottom: 20px; }
  h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .05em;
       color: #6b7280; margin: 24px 0 10px; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }
  table.stats { border-collapse: collapse; font-size: 13px; }
  table.stats td, table.stats th {
    border: 1px solid #e5e7eb; padding: 5px 10px; text-align: right; }
  table.stats th { background: #f3f4f6; text-align: center; }
  table.stats td:first-child, table.stats th:first-child { text-align: left; }
  .facts { display: flex; gap: 24px; flex-wrap: wrap; font-size: 14px; margin: 8px 0 4px; }
  .fact b { font-size: 20px; display: block; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 14px; }
  .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px; break-inside: avoid; }
  .card .depiction { height: 150px; display: flex; align-items: center; justify-content: center; }
  .card .depiction svg { max-width: 100%; max-height: 150px; }
  .card .name { font-weight: 600; margin-top: 6px; }
  .card .formula { color: #6b7280; font-size: 12px; }
  .card .props { list-style: none; padding: 0; margin: 6px 0 0; font-size: 12px; color: #374151; }
  .card .props li { display: flex; justify-content: space-between; }
  .card .props .k { color: #6b7280; }
  .truncated { color: #6b7280; font-size: 13px; margin-top: 12px; }
  @media print { body { padding: 0; } .card { border-color: #ccc; } }
"""


def _facts(summary: ReportSummary) -> str:
    """Render the headline number tiles."""
    tiles = [("Molecules", str(summary.n_molecules))]
    if summary.lipinski_pass is not None:
        tiles.append(("Pass Lipinski", str(summary.lipinski_pass)))
    if summary.n_clusters is not None:
        tiles.append(("Clusters", str(summary.n_clusters)))
    if summary.n_scaffolds is not None:
        tiles.append(("Scaffolds", str(summary.n_scaffolds)))
    return "".join(f'<div class="fact"><b>{v}</b>{html.escape(k)}</div>' for k, v in tiles)


def _stats_table(summary: ReportSummary) -> str:
    """Render the per-descriptor min/mean/max table, or empty if none."""
    if not summary.descriptor_stats:
        return "<p class='meta'>Descriptors were not computed for this dataset.</p>"
    rows = [
        f"<tr><td>{html.escape(s.spec.label)}</td>"
        f"<td>{s.minimum:.2f}</td><td>{s.mean:.2f}</td><td>{s.maximum:.2f}</td></tr>"
        for s in summary.descriptor_stats
    ]
    return (
        "<table class='stats'><tr><th>Descriptor</th><th>Min</th><th>Mean</th><th>Max</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _props(record: MoleculeRecord) -> str:
    """Render one molecule card's key/value list from whatever is computed."""
    pairs: list[tuple[str, str]] = []
    if record.descriptors is not None:
        for spec in DESCRIPTOR_SPECS:
            pairs.append((spec.label, spec.fmt.format(spec.getter(record.descriptors))))
    if record.cluster is not None:
        pairs.append(("Cluster", str(record.cluster.cluster_id)))
    items = "".join(
        f'<li><span class="k">{html.escape(k)}</span><span>{html.escape(v)}</span></li>'
        for k, v in pairs
    )
    return f'<ul class="props">{items}</ul>'


def _card(record: MoleculeRecord, include_depiction: bool) -> str:
    """Render one molecule card."""
    depiction = ""
    if include_depiction:
        try:
            depiction = render_svg(record.mol, 220, 150, dark=False)
        except Exception:  # noqa: BLE001 — a bad depiction must not abort the report
            logger.exception("Failed to depict %s for the report", record.name)
    return (
        '<div class="card">'
        f'<div class="depiction">{depiction}</div>'
        f'<div class="name">{html.escape(record.name)}</div>'
        f'<div class="formula">{html.escape(record.formula)}</div>'
        f"{_props(record)}"
        "</div>"
    )


def write_html(
    records: list[MoleculeRecord],
    summary: ReportSummary,
    config: ReportConfig,
    truncated: int,
    path: Path,
    progress: ProgressCallback,
) -> None:
    """Write a self-contained HTML report to ``path``."""
    cards = []
    for index, record in enumerate(records):
        cards.append(_card(record, config.include_depictions))
        progress(index + 1, len(records))

    truncation_note = (
        f'<p class="truncated">… and {truncated} more molecule(s) not shown '
        f"(summary covers all {summary.n_molecules}).</p>"
        if truncated > 0
        else ""
    )
    meta_line = (
        f"Generated {html.escape(summary.generated)} · Wawekit {html.escape(summary.version)}"
    )

    document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(summary.title)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{html.escape(summary.title)}</h1>
<div class="meta">{meta_line}</div>
<div class="facts">{_facts(summary)}</div>
<h2>Descriptor summary</h2>
{_stats_table(summary)}
<h2>Molecules</h2>
<div class="grid">{"".join(cards)}</div>
{truncation_note}
</body>
</html>"""

    path.write_text(document, encoding="utf-8")
    logger.info("Wrote HTML report to %s", path)
