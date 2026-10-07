"""Render a short plain-text summary of a ``DiffResult`` for the terminal."""

from collections import Counter

from pbi_report_validator.domain.models import Category, DiffResult
from pbi_report_validator.reporting.labels import data_overview, severity_overview

DEFAULT_LIMIT = 20


def format_summary(result: DiffResult, limit: int = DEFAULT_LIMIT) -> str:
    """Summarise findings: counts per category, then the first findings.

    Args:
        result: The diff result.
        limit: Maximum number of findings to list.

    Returns:
        Multi-line text without a trailing newline.
    """
    header = f"Compared {result.old_source} -> {result.new_source}"
    overview = data_overview(result)
    if overview:
        header += "\n" + overview
    if not result.findings:
        return f"{header}\nNo differences found."
    counts = Counter(f.category for f in result.findings)
    lines = [
        header,
        f"{len(result.findings)} findings ({severity_overview(result)}):",
    ]
    lines += [
        f"  {category.value:<12} {counts[category]}"
        for category in Category
        if counts[category]
    ]
    lines.append("")
    lines += [
        f"  {f.severity.value:<8} [{f.change.value}] {f.path}: {f.message}"
        for f in result.findings[:limit]
    ]
    hidden = len(result.findings) - limit
    if hidden > 0:
        lines.append(f"  ... and {hidden} more (use --json for the full list)")
    return "\n".join(lines)
