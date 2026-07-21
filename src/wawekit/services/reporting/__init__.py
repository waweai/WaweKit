"""Report generation: shareable HTML and PDF summaries of a dataset.

The public surface is :func:`~wawekit.services.reporting.report.generate_report`
plus the config/result types it uses.
"""

from wawekit.services.reporting.report import (
    ReportConfig,
    ReportFormat,
    ReportResult,
    ReportSummary,
    build_summary,
    generate_report,
)

__all__ = [
    "ReportConfig",
    "ReportFormat",
    "ReportResult",
    "ReportSummary",
    "build_summary",
    "generate_report",
]
