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


def default_severity(category: Category, change: ChangeKind) -> Severity:
    """The severity a finding of this category and change gets by default."""
    return CHANGE_SEVERITY.get((category, change), CATEGORY_SEVERITY[category])


def with_severity(findings: Iterable[Finding]) -> list[Finding]:
    """Copies of the findings with their default severity set."""
    return [
        f.model_copy(update={"severity": default_severity(f.category, f.change)})
        for f in findings
    ]


def at_least(findings: Iterable[Finding], threshold: Severity) -> list[Finding]:
    """The findings whose severity is ``threshold`` or higher."""
    levels = list(Severity)
    return [f for f in findings if levels.index(f.severity) >= levels.index(threshold)]
