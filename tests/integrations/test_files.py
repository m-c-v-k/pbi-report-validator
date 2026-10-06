import shutil
from pathlib import Path

import pytest

from pbi_report_validator.integrations.files import (
    InvalidJsonError,
    MissingDefinitionError,
    ProjectNotFoundError,
    load_project,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def project_copy(tmp_path: Path) -> Path:
    target = tmp_path / "sales"
    shutil.copytree(FIXTURES / "sales_v1", target)
    return target


def test_loads_sales_v1_report_and_model() -> None:
    project = load_project(FIXTURES / "sales_v1")

    assert project.name == "Sales"
    assert project.report.path == "Sales.Report"
    assert project.report.report.path == "Sales.Report/definition/report.json"
    assert project.report.pages_meta is not None
    assert [p.name for p in project.report.pages] == ["details", "overview"]
    overview = project.report.pages[1]
    assert [v.path.split("/")[-2] for v in overview.visuals] == [
        "card_margin",
        "card_total_sales",
        "chart_sales_by_month",
        "slicer_year",
    ]
    assert project.semantic_model is not None
    assert [
        f.path.removeprefix("Sales.SemanticModel/definition/")
        for f in project.semantic_model.files
    ] == [
        "database.tmdl",
        "model.tmdl",
        "relationships.tmdl",
        "tables/Date.tmdl",
        "tables/Product.tmdl",
        "tables/Sales.tmdl",
    ]


def test_loads_sales_v2_with_added_page() -> None:
    project = load_project(FIXTURES / "sales_v2")

    assert [p.name for p in project.report.pages] == ["details", "overview", "trends"]


def test_accepts_report_folder_directly() -> None:
    project = load_project(FIXTURES / "sales_v1" / "Sales.Report")

    assert project.name == "Sales"
    assert project.semantic_model is not None


def test_output_is_identical_between_runs() -> None:
    first = load_project(FIXTURES / "sales_v1")
    second = load_project(FIXTURES / "sales_v1")

    assert first.model_dump_json() == second.model_dump_json()


def test_missing_folder_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFoundError):
        load_project(tmp_path / "does-not-exist")


def test_folder_without_report_raises(tmp_path: Path) -> None:
    with pytest.raises(ProjectNotFoundError, match="found none"):
        load_project(tmp_path)


def test_missing_definition_raises(project_copy: Path) -> None:
    (project_copy / "Sales.Report" / "definition" / "report.json").unlink()

    with pytest.raises(MissingDefinitionError):
        load_project(project_copy)


def test_broken_report_json_raises(project_copy: Path) -> None:
    (project_copy / "Sales.Report" / "definition" / "report.json").write_text("{")

    with pytest.raises(InvalidJsonError) as exc_info:
        load_project(project_copy)

    assert exc_info.value.path == "Sales.Report/definition/report.json"


def test_broken_visual_json_is_kept_with_error(project_copy: Path) -> None:
    visual = (
        project_copy
        / "Sales.Report/definition/pages/overview/visuals/card_margin/visual.json"
    )
    visual.write_text("not json")

    project = load_project(project_copy)

    overview = next(p for p in project.report.pages if p.name == "overview")
    broken = overview.visuals[0]
    assert broken.error is not None
    assert broken.content == {}


def test_model_is_none_without_dataset_path(project_copy: Path) -> None:
    pbir = project_copy / "Sales.Report" / "definition.pbir"
    pbir.write_text('{"datasetReference": {"byConnection": {}}}')

    project = load_project(project_copy)

    assert project.semantic_model is None
