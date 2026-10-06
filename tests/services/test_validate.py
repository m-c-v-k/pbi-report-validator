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
    assert any(
        f.category == Category.VISUAL and f.change == ChangeKind.REMOVED
        for f in result.findings
    )


def test_measures_are_skipped_without_semantic_model(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v2", new)
    (new / "Sales.Report/definition.pbir").write_text(
        '{"datasetReference": {"byConnection": {}}}'
    )

    result = validate(FIXTURES / "sales_v1", new)

    assert not any(f.category == Category.MEASURE for f in result.findings)
    assert any(f.category == Category.PAGE for f in result.findings)
