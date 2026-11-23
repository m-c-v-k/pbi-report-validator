import pytest

from pbi_report_validator.domain.models import (
    AiExplanation,
    AiMode,
    Category,
    ChangedResult,
    ChangeKind,
    DiffResult,
    Finding,
    ProjectRun,
    ProjectStatus,
    Severity,
)
from pbi_report_validator.reporting.markdown import (
    NO_MENTION,
    changed_to_markdown,
    escape,
    to_markdown,
)


def finding(path: str, **kwargs: str | None) -> Finding:
    values = {"message": "changed", "old": None, "new": None, **kwargs}
    return Finding(
        category=Category.MEASURE,
        change=ChangeKind.MODIFIED,
        severity=Severity.INFO,
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


def test_ai_mode_is_stated_only_when_on() -> None:
    off = DiffResult(old_source="o", new_source="n")
    on = off.model_copy(update={"ai_mode": AiMode.API, "ai_model": "claude-x"})

    assert "AI:" not in to_markdown(off)
    assert "AI: api (claude-x)." in to_markdown(on)


def test_finding_messages_cannot_mention_users() -> None:
    text = to_markdown(result(finding("p/v", message="Visual 'Ask @data-team' moved")))

    assert "@data-team" not in text
    assert f"Ask {NO_MENTION}data-team" in text


def test_ai_notes_cannot_mention_users() -> None:
    explained = finding("p/v").model_copy(
        update={"explanation": AiExplanation(text="Ask @octocat about it")}
    )

    text = to_markdown(result(explained))

    assert "@octocat" not in text
    assert "AI-generated: Ask @​octocat" in text


def changed(*runs: ProjectRun) -> ChangedResult:
    return ChangedResult(base="origin/develop", projects=runs)


def compared(path: str, *findings: Finding) -> ProjectRun:
    return ProjectRun(path=path, status=ProjectStatus.CHANGED, result=result(*findings))


def test_changed_run_without_projects() -> None:
    text = changed_to_markdown(changed())

    assert text == (
        "## Power BI report diff: changed since `origin/develop`\n\n"
        "No reports or semantic models changed.\n"
    )


def test_changed_run_has_a_table_and_one_block_per_compared_project() -> None:
    text = changed_to_markdown(
        changed(
            compared("b/B.Report", finding("model/T/m")),
            ProjectRun(path="a/A.Report", status=ProjectStatus.ADDED),
            ProjectRun(path="c/C.Report", status=ProjectStatus.ERROR, message="bad"),
        )
    )

    assert "3 projects · Severity: 0 critical, 0 warning, 1 info" in text
    assert text.index("| `a/A.Report` | added |  |  |  |") < text.index(
        "| `b/B.Report` | changed | 0 | 0 | 1 |"
    )
    assert "- `c/C.Report` (error): bad" in text
    assert text.count("<details><summary><code>") == 1
    assert "<code>b/B.Report</code> · 1 finding</summary>" in text
    assert text.count("## Power BI report diff") == 1


def test_changed_run_escapes_paths_and_messages() -> None:
    text = changed_to_markdown(
        changed(
            compared("a|b/<X>.Report"),
            ProjectRun(path="s", status=ProjectStatus.SKIPPED, message="@team *x*"),
        )
    )

    assert r"| `a\|b/<X>.Report` |" in text
    assert "<code>a|b/&lt;X&gt;.Report</code>" in text
    assert rf"{NO_MENTION}team \*x\*" in text


def test_changed_run_shares_the_limit_between_projects() -> None:
    many = [finding(f"model/T/m{i:04}", old="x" * 50, new="y" * 50) for i in range(300)]
    runs = [compared(f"p{i}/P.Report", *many) for i in range(5)]

    text = changed_to_markdown(changed(*runs), limit=60_000)

    assert len(text) < 60_000
    assert text.count("<details><summary><code>") == 5
    assert text.count("more findings not shown") == 5
    assert "not shown in detail" not in text


def test_changed_run_counts_projects_that_do_not_fit() -> None:
    runs = [compared(f"p{i:02}/P.Report", finding("model/T/m")) for i in range(50)]

    text = changed_to_markdown(changed(*runs), limit=8_000)

    assert len(text) < 8_000
    shown = text.count("<details><summary><code>")
    assert 0 < shown < 50
    assert "<code>p00/P.Report</code>" in text
    hidden = 50 - shown
    assert f"_{hidden} more projects not shown in detail; see the JSON" in text
