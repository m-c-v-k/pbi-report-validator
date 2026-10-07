import pytest

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


def test_fence_is_longer_than_backtick_runs_in_value() -> None:
    value = "a ```b``` ~~~~ ````c```` " + "x" * 90

    text = to_markdown(result(finding("m", old=value, new=None)))

    assert "  `````\n" in text
    assert "  _(none)_" in text


def test_ampersand_is_escaped_as_entity() -> None:
    text = to_markdown(result(finding("p/v", message="Sales &amp; Cost & more")))

    assert "Sales &amp;amp; Cost &amp; more" in text


def test_multiline_message_stays_on_one_list_line() -> None:
    text = to_markdown(result(finding("p/v", message="first\n# heading\n- item")))

    assert "first \\# heading - item" in text


@pytest.mark.parametrize(("count", "noun"), [(2, "finding"), (3, "findings")])
def test_footer_noun_matches_count(count: int, noun: str) -> None:
    many = [finding(f"m{i}", old="x" * 50, new="y" * 50) for i in range(count)]
    header_only = len(to_markdown(result(*many), limit=10**6).split("### ")[0])

    text = to_markdown(result(*many), limit=header_only + 1_200)

    assert f"_{count - 1} more {noun} not shown;" in text


def test_default_limit_keeps_output_under_github_maximum() -> None:
    many = [
        finding(f"model/T/m{i:05}", old="x" * 70, new="y" * 70) for i in range(5000)
    ]

    assert len(to_markdown(result(*many))) < 65_536


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


def test_severity_overview_and_per_finding() -> None:
    text = to_markdown(result(finding("model/Sales/M")))

    assert "Severity: 0 critical, 0 warning, 1 info\n" in text
    assert "- info · **modified** `model/Sales/M`: changed" in text
