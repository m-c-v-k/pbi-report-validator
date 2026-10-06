"""Render a short plain-text summary of a ``DiffResult`` for the terminal."""

from collections import Counter

from pbi_report_validator.domain.models import Category, DataStatus, DiffResult

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
    lines = [header, f"{len(result.findings)} findings:"]
    lines += [
        f"  {category.value:<12} {counts[category]}"
        for category in Category
        if counts[category]
    ]
    lines.append("")
    lines += [
        f"  [{f.change.value}] {f.path}: {f.message}" for f in result.findings[:limit]
    ]
    hidden = len(result.findings) - limit
    if hidden > 0:
        lines.append(f"  ... and {hidden} more (use --json for the full list)")
    return "\n".join(lines)


def data_overview(result: DiffResult) -> str | None:
    """One line about data validation, or ``None`` if it did not run."""
    if not result.data:
        return None
    counts = Counter(summary.status for summary in result.data)
    return (
        f"Data: {len(result.data)} visuals compared, "
        f"{counts[DataStatus.SAME]} same, {counts[DataStatus.DIFFERENT]} different, "
        f"{counts[DataStatus.NOT_VALIDATED]} not validated"
    )
