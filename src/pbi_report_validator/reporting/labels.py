"""Labels and summary text shared by the terminal, Markdown and HTML reports."""

from collections import Counter

from pbi_report_validator.domain.models import (
    Category,
    DataStatus,
    DiffResult,
    ItemStatus,
)

CATEGORY_LABELS = {
    Category.PAGE: "Pages",
    Category.VISUAL: "Visuals",
    Category.FIELD: "Fields",
    Category.FILTER: "Filters",
    Category.SLICER: "Slicers",
    Category.MEASURE: "Measures",
    Category.PARSE_ISSUE: "Parse issues",
    Category.DATA: "Data",
}
STATUS_LABELS = {
    ItemStatus.ADDED: "Added",
    ItemStatus.REMOVED: "Removed",
    ItemStatus.MODIFIED: "Modified",
    ItemStatus.UNCHANGED: "Unchanged",
}
# A text mark next to the colour, so status is not conveyed by colour alone.
STATUS_MARKS = {
    ItemStatus.ADDED: "+",
    ItemStatus.REMOVED: "-",
    ItemStatus.MODIFIED: "~",
    ItemStatus.UNCHANGED: "",
}


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
