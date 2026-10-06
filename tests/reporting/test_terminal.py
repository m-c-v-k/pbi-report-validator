from pbi_report_validator.domain.models import Category, ChangeKind, DiffResult, Finding
from pbi_report_validator.reporting.terminal import format_summary


def finding(path: str) -> Finding:
    return Finding(
        category=Category.VISUAL, change=ChangeKind.ADDED, path=path, message="added"
    )


def test_summary_truncates_long_lists() -> None:
    result = DiffResult(
        old_source="a",
        new_source="b",
        findings=tuple(finding(f"p/v{i}") for i in range(3)),
    )

    text = format_summary(result, limit=2)

    assert text.splitlines() == [
        "Compared a -> b",
        "3 findings:",
        "  visual       3",
        "",
        "  [added] p/v0: added",
        "  [added] p/v1: added",
        "  ... and 1 more (use --json for the full list)",
    ]


def test_summary_without_findings() -> None:
    result = DiffResult(old_source="a", new_source="b")

    assert format_summary(result) == "Compared a -> b\nNo differences found."
