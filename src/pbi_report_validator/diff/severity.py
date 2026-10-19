"""Default severity of findings, from their category and kind of change."""

from collections.abc import Iterable
from typing import Final

from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Finding,
    Severity,
)

CATEGORY_SEVERITY: Final = {
    Category.PAGE: Severity.INFO,
    Category.VISUAL: Severity.INFO,
    Category.FIELD: Severity.WARNING,
    Category.FILTER: Severity.CRITICAL,
    Category.SLICER: Severity.CRITICAL,
    Category.MEASURE: Severity.WARNING,
    Category.PARSE_ISSUE: Severity.WARNING,
    Category.DATA: Severity.CRITICAL,
}
# Changes that matter more or less than the default of their category.
CHANGE_SEVERITY: Final = {
    (Category.PAGE, ChangeKind.REMOVED): Severity.CRITICAL,
    (Category.VISUAL, ChangeKind.REMOVED): Severity.CRITICAL,
    (Category.VISUAL, ChangeKind.RETYPED): Severity.WARNING,
    (Category.MEASURE, ChangeKind.ADDED): Severity.INFO,
    (Category.MEASURE, ChangeKind.MODIFIED): Severity.CRITICAL,
    (Category.DATA, ChangeKind.ERROR): Severity.WARNING,
}
# Rank of each severity for thresholds, from the enum's least-to-most order.
SEVERITY_RANK: Final = {severity: rank for rank, severity in enumerate(Severity)}


def default_severity(category: Category, change: ChangeKind) -> Severity:
    """The severity a finding of this category and change gets by default."""
    return CHANGE_SEVERITY.get((category, change), CATEGORY_SEVERITY[category])


def make_finding(
    category: Category,
    change: ChangeKind,
    *,
    path: str,
    message: str,
    old: str | None = None,
    new: str | None = None,
    visual: str | None = None,
) -> Finding:
    """A finding with the default severity of its category and change."""
    return Finding(
        category=category,
        change=change,
        severity=default_severity(category, change),
        path=path,
        message=message,
        old=old,
        new=new,
        visual=visual,
    )


def at_least(findings: Iterable[Finding], threshold: Severity) -> list[Finding]:
    """The findings whose severity is ``threshold`` or higher."""
    minimum = SEVERITY_RANK[threshold]
    return [f for f in findings if SEVERITY_RANK[f.severity] >= minimum]
