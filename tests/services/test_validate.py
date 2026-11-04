import shutil
from pathlib import Path

import pytest

from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataSettings,
    DiffResult,
    Finding,
    Severity,
)
from pbi_report_validator.services.data_validation import InvalidDataOptionsError
from pbi_report_validator.services.validate import failure_reasons, validate
from tests.factories import FIXTURES


def test_parse_issues_become_findings(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v1", new)
    visual = (
        new / "Sales.Report/definition/pages/overview/visuals/card_margin/visual.json"
    )
    visual.write_text("{")

    result = validate(FIXTURES / "sales_v1", new)

    issues = [f for f in result.findings if f.category == Category.PARSE_ISSUE]
    assert [(f.change, f.path) for f in issues] == [
        (
            ChangeKind.ERROR,
            "new/Sales.Report/definition/pages/overview/visuals/card_margin/visual.json",
        )
    ]
    assert not any(f.category == Category.VISUAL for f in result.findings)
    assert [f.visual_path for f in issues] == ["overview/card_margin"]


def test_missing_semantic_model_is_reported_not_compared(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v2", new)
    (new / "Sales.Report/definition.pbir").write_text(
        '{"datasetReference": {"byConnection": {}}}'
    )
    shutil.rmtree(new / "Sales.SemanticModel")

    result = validate(FIXTURES / "sales_v1", new)

    assert not any(f.category == Category.MEASURE for f in result.findings)
    assert any(f.category == Category.PAGE for f in result.findings)
    [warning] = [f for f in result.findings if f.path == "new/model"]
    assert warning.severity == Severity.WARNING
    assert warning.message == (
        "Measures were not compared: in the new version, "
        "the report uses a published semantic model (byConnection)"
    )


def test_unreadable_tmdl_is_a_parse_issue_not_a_stopped_run(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v2", new)
    (new / "Sales.SemanticModel/definition/tables/Sales.tmdl").write_bytes(b"\xff")

    result = validate(FIXTURES / "sales_v1", new)

    issues = [f for f in result.findings if f.category == Category.PARSE_ISSUE]
    assert [f.path for f in issues] == [
        "new/Sales.SemanticModel/definition/tables/Sales.tmdl"
    ]
    assert issues[0].message.startswith("Could not fully parse the new version")


def test_unparseable_visual_in_old_version_is_not_reported_added(
    tmp_path: Path,
) -> None:
    old = tmp_path / "old"
    shutil.copytree(FIXTURES / "sales_v1", old)
    visual = (
        old / "Sales.Report/definition/pages/overview/visuals/card_margin/visual.json"
    )
    visual.write_text("{")

    result = validate(old, FIXTURES / "sales_v1")

    assert [(f.category, f.path.split("/")[0]) for f in result.findings] == [
        (Category.PARSE_ISSUE, "old")
    ]


def test_unparseable_visual_on_page_with_new_id_is_not_reported_removed(
    tmp_path: Path,
) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v1", new)
    pages = new / "Sales.Report/definition/pages"
    (pages / "overview").rename(pages / "overview_2")
    for file in (pages / "pages.json", pages / "overview_2/page.json"):
        text = file.read_text(encoding="utf-8")
        file.write_text(text.replace('"overview"', '"overview_2"'), encoding="utf-8")
    (pages / "overview_2/visuals/card_margin/visual.json").write_text("{")

    result = validate(FIXTURES / "sales_v1", new)

    removed = [f for f in result.findings if f.change == ChangeKind.REMOVED]
    issues = [f for f in result.findings if f.category == Category.PARSE_ISSUE]
    assert removed == []
    assert [f.visual_path for f in issues] == ["overview/card_margin"]


def test_tmdl_issues_become_findings(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v1", new)
    tmdl = new / "Sales.SemanticModel/definition/tables/Sales.tmdl"
    tmdl.write_text(tmdl.read_text(encoding="utf-8") + "\tmeasure Broken\n")

    result = validate(FIXTURES / "sales_v1", new)

    issues = [f for f in result.findings if f.category == Category.PARSE_ISSUE]
    assert len(issues) == 1
    assert issues[0].path.startswith(
        "new/Sales.SemanticModel/definition/tables/Sales.tmdl:"
    )


def result_with(*findings: Finding) -> DiffResult:
    return DiffResult(old_source="old", new_source="new", findings=findings)


WARNING = Finding(
    category=Category.FIELD,
    change=ChangeKind.ADDED,
    severity=Severity.WARNING,
    path="p/v/fields/x",
    message="m",
)
DATA_ERROR = Finding(
    category=Category.DATA,
    change=ChangeKind.ERROR,
    severity=Severity.WARNING,
    path="p/v/data",
    message="m",
)


@pytest.mark.parametrize(
    ("fail_on", "fail_on_data_error", "expected"),
    [
        (None, False, []),
        (Severity.CRITICAL, False, []),
        (
            Severity.WARNING,
            False,
            ["Failed: 2 findings at warning or above (--fail-on warning)"],
        ),
        (
            None,
            True,
            ["Failed: data of 1 visual not fully validated (--fail-on-data-error)"],
        ),
    ],
)
def test_failure_reasons(
    fail_on: Severity | None, fail_on_data_error: bool, expected: list[str]
) -> None:
    result = result_with(WARNING, DATA_ERROR)

    assert failure_reasons(result, fail_on, fail_on_data_error) == expected


def test_a_failed_ai_call_does_not_fail_the_run() -> None:
    ai_error = Finding(
        category=Category.AI,
        change=ChangeKind.ERROR,
        severity=Severity.INFO,
        path="ai/match",
        message="m",
    )

    assert failure_reasons(result_with(ai_error), Severity.INFO, False) == []


def test_data_settings_without_runner_is_rejected() -> None:
    settings = DataSettings(old_dataset="a", new_dataset="b")

    with pytest.raises(InvalidDataOptionsError):
        validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", settings)
