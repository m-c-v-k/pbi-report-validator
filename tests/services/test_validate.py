import shutil
from pathlib import Path

from pbi_report_validator.domain.models import Category, ChangeKind
from pbi_report_validator.services.validate import validate

FIXTURES = Path(__file__).parent.parent / "fixtures"


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


def test_measures_are_skipped_without_semantic_model(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v2", new)
    (new / "Sales.Report/definition.pbir").write_text(
        '{"datasetReference": {"byConnection": {}}}'
    )

    result = validate(FIXTURES / "sales_v1", new)

    assert not any(f.category == Category.MEASURE for f in result.findings)
    assert any(f.category == Category.PAGE for f in result.findings)


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
