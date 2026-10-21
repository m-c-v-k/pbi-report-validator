"""Labels and summary text shared by the terminal, Markdown and HTML reports."""

from collections import Counter

from pbi_report_validator.domain.models import (
    AiMode,
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
    Category.AI: "AI",
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

# Shown in every report when row-level data was not masked (--show-data-values).
UNMASKED_WARNING = (
    "This report contains unmasked row-level data: the keys and values of the "
    "compared rows. Do not publish it, attach it to a pull request or share it "
    "outside the people allowed to see the datasets."
)

# Every piece of AI output carries this label (AI_LABEL), and every report
# made with --ai api says so.
AI_LABEL = "AI-generated"


def severity_overview(result: DiffResult) -> str:
    """Findings per severity, most severe first: ``1 critical, 0 warning, 2 info``."""
    counts = result.severity_counts
    return f"{counts.critical} critical, {counts.warning} warning, {counts.info} info"


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


def ai_overview(result: DiffResult) -> str | None:
    """One line saying the AI layer was on, or ``None`` if it was off."""
    if result.ai_mode is AiMode.OFF:
        return None
    suggestions = len(result.ai_suggestions)
    renames = f" {suggestions} rename suggestions." if suggestions else ""
    return (
        f"AI: {result.ai_mode.value} ({result.ai_model}).{renames} "
        f"AI output is labelled '{AI_LABEL}'; the findings themselves are not."
    )


def ai_notes(result: DiffResult) -> dict[tuple[Category, str], str]:
    """AI rename suggestions as notes, keyed by category and finding path.

    The removed object's finding gets "renamed to", the added one's
    "renamed from"; both are labelled as AI output.
    """
    notes = {}
    for s in result.ai_suggestions:
        tail = f"(confidence {s.confidence:.0%}): {s.reason}"
        notes[s.category, s.old_path] = (
            f"{AI_LABEL}: probably renamed to {s.new_path} {tail}"
        )
        notes[s.category, s.new_path] = (
            f"{AI_LABEL}: probably renamed from {s.old_path} {tail}"
        )
    return notes
