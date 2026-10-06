from pbi_report_validator.domain.models import Category, ChangeKind, DiffResult, Finding
from pbi_report_validator.reporting.markdown import escape, to_markdown


def finding(path: str, **kwargs: str | None) -> Finding:
    values = {"message": "changed", "old": None, "new": None, **kwargs}
    return Finding(
        category=Category.MEASURE,
        change=ChangeKind.MODIFIED,
        path=path,
        message=values["message"] or "",
        old=values["old"],
        new=values["new"],
    )


def result(*findings: Finding) -> DiffResult:
    return DiffResult(old_source="old", new_source="new", findings=findings)


def test_no_findings() -> None:
    assert to_markdown(result()).endswith("· 0 findings\n\nNo differences found.\n")


def test_special_characters_are_escaped_in_text() -> None:
    text = to_markdown(result(finding("p/v", message="a|b *c* _d_ <e> `f` [g]")))

    assert r"a\|b \*c\* \_d\_ \<e\> \`f\` \[g\]" in text


def test_backticks_cannot_break_code_spans() -> None:
    text = to_markdown(result(finding("p/`v`", old="x`y", new="z")))

    assert "`p/'v'`" in text
    assert "`x'y`" in text


def test_long_or_multiline_values_are_collapsible() -> None:
    dax = "DIVIDE(\n    SUM(Sales[Amount]),\n    2\n)"

    text = to_markdown(result(finding("model/Sales/M", old=dax, new="1")))

    assert "<details><summary>Old → new</summary>" in text
    assert "  ```\n  DIVIDE(\n      SUM(Sales[Amount]),\n      2\n  )\n  ```" in text


def test_value_containing_fence_uses_tildes() -> None:
    text = to_markdown(result(finding("m", old="a ```b``` " + "x" * 90, new=None)))

    assert "  ~~~~\n" in text
    assert "  _(none)_" in text


def test_truncates_to_limit_with_note() -> None:
    many = [
        finding(f"model/T/m{i:04}", old="x" * 50, new="y" * 50) for i in range(2000)
    ]

    text = to_markdown(result(*many), limit=20_000)

    assert len(text) < 20_000
    assert "more findings not shown; see the JSON output for the full list." in text
    assert "m0000" in text
    assert "m1999" not in text


def test_escape_leaves_plain_text() -> None:
    assert escape("Total Sales 2025") == "Total Sales 2025"
