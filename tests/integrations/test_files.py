import json
import shutil
from pathlib import Path

import pytest

from pbi_report_validator.domain.raw import (
    InputFormat,
    RawLegacyReport,
    RawPage,
    RawProject,
)
from pbi_report_validator.integrations.files import (
    InvalidJsonError,
    MissingDefinitionError,
    ModelOutsideProjectError,
    ProjectNotFoundError,
    UnreadableFolderError,
    UnsupportedInputError,
    detect_input,
    load_project,
)
from tests.factories import FIXTURES


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


BY_CONNECTION = json.dumps(
    {"datasetReference": {"byConnection": {"connectionString": "Data Source=x"}}}
)


def test_by_connection_without_sibling_model_gives_no_model(
    project_copy: Path,
) -> None:
    (project_copy / "Sales.Report" / "definition.pbir").write_text(BY_CONNECTION)
    shutil.rmtree(project_copy / "Sales.SemanticModel")

    project = load_project(project_copy)

    assert project.semantic_model is None
    assert project.model_missing == (
        "the report uses a published semantic model (byConnection)"
    )


def test_by_connection_uses_the_sibling_model(project_copy: Path) -> None:
    (project_copy / "Sales.Report" / "definition.pbir").write_text(BY_CONNECTION)

    project = load_project(project_copy)

    assert project.model_missing is None
    assert project.semantic_model is not None
    assert project.semantic_model.path == "Sales.SemanticModel"
    assert project.semantic_model == load_project(FIXTURES / "sales_v1").semantic_model


@pytest.mark.parametrize("reference", ["null", '"x"', '{"byPath": null}'])
def test_model_is_none_with_malformed_dataset_reference(
    project_copy: Path, reference: str
) -> None:
    pbir = project_copy / "Sales.Report" / "definition.pbir"
    pbir.write_text(f'{{"datasetReference": {reference}}}')

    project = load_project(project_copy)

    assert project.semantic_model is None


def overview_visual(project_copy: Path, name: str) -> Path:
    pages = project_copy / "Sales.Report/definition/pages"
    return pages / "overview/visuals" / name / "visual.json"


def overview_page(project: RawProject) -> RawPage:
    return next(p for p in project.report.pages if p.name == "overview")


def test_broken_page_json_is_kept_with_error(project_copy: Path) -> None:
    (project_copy / "Sales.Report/definition/pages/details/page.json").write_text("{")

    project = load_project(project_copy)

    details = next(p for p in project.report.pages if p.name == "details")
    assert details.page.error is not None


def test_broken_pages_json_raises(project_copy: Path) -> None:
    (project_copy / "Sales.Report/definition/pages/pages.json").write_text("[")

    with pytest.raises(InvalidJsonError):
        load_project(project_copy)


def test_broken_definition_pbir_raises(project_copy: Path) -> None:
    (project_copy / "Sales.Report/definition.pbir").write_text("{")

    with pytest.raises(InvalidJsonError):
        load_project(project_copy)


def test_non_object_json_is_an_error(project_copy: Path) -> None:
    overview_visual(project_copy, "card_margin").write_text("[1, 2]")

    visual = overview_page(load_project(project_copy)).visuals[0]

    assert visual.error == "top-level value is not an object"


def test_non_utf8_visual_is_kept_with_error(project_copy: Path) -> None:
    overview_visual(project_copy, "card_margin").write_bytes(b'{"name": "\xff"}')

    visual = overview_page(load_project(project_copy)).visuals[0]

    assert visual.error is not None


def test_non_utf8_tmdl_is_kept_with_error(project_copy: Path) -> None:
    tmdl = project_copy / "Sales.SemanticModel/definition/tables/Sales.tmdl"
    tmdl.write_bytes(b"table \xff")

    model = load_project(project_copy).semantic_model

    assert model is not None
    sales = next(f for f in model.files if f.path.endswith("Sales.tmdl"))
    assert sales.error is not None
    assert sales.text == ""


def test_model_bim_is_loaded_when_there_is_no_tmdl(project_copy: Path) -> None:
    model_dir = project_copy / "Sales.SemanticModel"
    shutil.rmtree(model_dir / "definition")
    (model_dir / "model.bim").write_text('{"model": {"tables": []}}')

    project = load_project(project_copy)

    assert project.model_missing is None
    assert project.semantic_model is not None
    assert project.semantic_model.files == ()
    assert project.semantic_model.bim is not None
    assert project.semantic_model.bim.path == "Sales.SemanticModel/model.bim"
    assert project.semantic_model.bim.content == {"model": {"tables": []}}


def test_tmdl_wins_over_model_bim(project_copy: Path) -> None:
    (project_copy / "Sales.SemanticModel" / "model.bim").write_text("{}")

    model = load_project(project_copy).semantic_model

    assert model is not None and model.bim is None and model.files


def test_model_without_tmdl_or_bim_gives_no_model(project_copy: Path) -> None:
    shutil.rmtree(project_copy / "Sales.SemanticModel" / "definition")

    project = load_project(project_copy)

    assert project.semantic_model is None
    assert project.model_missing == (
        "Sales.SemanticModel has no .tmdl files and no model.bim"
    )


def test_json_with_bom_is_read(project_copy: Path) -> None:
    path = overview_visual(project_copy, "card_margin")
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())

    visual = overview_page(load_project(project_copy)).visuals[0]

    assert visual.error is None
    assert visual.content["name"] == "card_margin"


def test_sibling_model_is_used_without_definition_pbir(project_copy: Path) -> None:
    (project_copy / "Sales.Report/definition.pbir").unlink()

    project = load_project(project_copy)

    assert project.semantic_model is not None
    assert project.semantic_model.path == "Sales.SemanticModel"


def test_model_path_to_missing_folder_gives_no_model(project_copy: Path) -> None:
    (project_copy / "Sales.Report/definition.pbir").write_text(
        '{"datasetReference": {"byPath": {"path": "../Missing.SemanticModel"}}}'
    )

    project = load_project(project_copy)

    assert project.semantic_model is None
    assert (
        project.model_missing
        == "definition.pbir points to a folder that does not exist"
    )


def write_model_path(project_copy: Path, model_path: str) -> None:
    (project_copy / "Sales.Report/definition.pbir").write_text(
        json.dumps({"datasetReference": {"byPath": {"path": model_path}}})
    )


def test_model_in_sibling_folder_outside_project_raises(project_copy: Path) -> None:
    shutil.move(project_copy / "Sales.SemanticModel", project_copy.parent / "Shared")
    write_model_path(project_copy, "../../Shared")

    with pytest.raises(ModelOutsideProjectError, match="outside the project"):
        load_project(project_copy)


def test_absolute_model_path_outside_project_raises(
    project_copy: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "elsewhere.SemanticModel"
    shutil.copytree(project_copy / "Sales.SemanticModel", outside)
    write_model_path(project_copy, str(outside.resolve()))

    with pytest.raises(ModelOutsideProjectError):
        load_project(project_copy)


def test_model_path_climbing_to_filesystem_root_raises(project_copy: Path) -> None:
    write_model_path(project_copy, "../../../../../../../../../..")

    with pytest.raises(ModelOutsideProjectError):
        load_project(project_copy)


def test_absolute_model_path_inside_project_is_allowed(project_copy: Path) -> None:
    write_model_path(
        project_copy, str((project_copy / "Sales.SemanticModel").resolve())
    )

    project = load_project(project_copy)

    assert project.semantic_model is not None
    assert project.semantic_model.path == "Sales.SemanticModel"


@pytest.mark.parametrize("method", ["glob", "iterdir", "rglob"])
def test_unreadable_folder_raises(
    project_copy: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    def deny(self: Path, *args: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, method, deny)

    with pytest.raises(UnreadableFolderError, match="Permission denied") as info:
        load_project(project_copy)
    assert info.value.path


def test_legacy_report_is_loaded_as_one_document() -> None:
    project = load_project(FIXTURES / "sales_v1_legacy")

    assert isinstance(project.report, RawLegacyReport)
    assert project.report.layout.path == "Sales.Report/report.json"
    assert "sections" in project.report.layout.content
    assert project.semantic_model is not None


def test_broken_legacy_report_raises(tmp_path: Path) -> None:
    copy = tmp_path / "legacy"
    shutil.copytree(FIXTURES / "sales_v1_legacy", copy)
    (copy / "Sales.Report" / "report.json").write_text("{")

    with pytest.raises(InvalidJsonError):
        load_project(copy)


def test_report_without_any_definition_names_both_formats(
    project_copy: Path,
) -> None:
    shutil.rmtree(project_copy / "Sales.Report" / "definition")

    with pytest.raises(MissingDefinitionError, match=r"nor report.json"):
        load_project(project_copy)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("sales_v1", InputFormat.PBIP_PBIR),
        ("sales_v1/Sales.Report", InputFormat.PBIP_PBIR),
        ("sales_v1/Sales.pbip", InputFormat.PBIP_PBIR),
        ("sales_v1_legacy", InputFormat.PBIP_LEGACY),
        ("sales_v1_legacy/Sales.Report", InputFormat.PBIP_LEGACY),
        ("sales_v1_legacy/Sales.pbip", InputFormat.PBIP_LEGACY),
        ("sales_v1/Sales.SemanticModel", InputFormat.SEMANTIC_MODEL),
    ],
)
def test_detect_fixture_inputs(relative: str, expected: InputFormat) -> None:
    assert detect_input(FIXTURES / relative) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Sales.pbit", InputFormat.PBIT),
        ("Sales.PBIX", InputFormat.PBIX),
        ("Sales.zip", InputFormat.UNKNOWN),
    ],
)
def test_detect_files_by_extension(
    tmp_path: Path, name: str, expected: InputFormat
) -> None:
    (tmp_path / name).write_bytes(b"PK")

    assert detect_input(tmp_path / name) is expected


def test_folder_with_only_a_model_is_a_semantic_model(tmp_path: Path) -> None:
    shutil.copytree(
        FIXTURES / "sales_v1/Sales.SemanticModel", tmp_path / "Sales.SemanticModel"
    )

    assert detect_input(tmp_path) is InputFormat.SEMANTIC_MODEL


@pytest.mark.parametrize(
    ("name", "reason"),
    [
        ("Sales.pbit", ".pbit files are not supported yet"),
        ("Sales.pbix", ".pbix files are not supported yet"),
        ("notes.txt", "not a supported input"),
    ],
)
def test_unsupported_files_name_the_input(
    tmp_path: Path, name: str, reason: str
) -> None:
    (tmp_path / name).write_bytes(b"PK")

    with pytest.raises(UnsupportedInputError) as exc_info:
        load_project(tmp_path / name)

    assert str(exc_info.value).startswith(f"{tmp_path / name}: {reason}")


def test_semantic_model_alone_is_unsupported() -> None:
    with pytest.raises(UnsupportedInputError, match="semantic model on its own"):
        load_project(FIXTURES / "sales_v1/Sales.SemanticModel")


def test_pbip_file_loads_its_project() -> None:
    from_file = load_project(FIXTURES / "sales_v1/Sales.pbip")
    from_folder = load_project(FIXTURES / "sales_v1")

    assert from_file.model_dump_json() == from_folder.model_dump_json()


@pytest.mark.parametrize(
    ("artifacts", "message"),
    [
        ([], "lists no report"),
        ([{"report": {"path": "Missing.Report"}}], "points to missing"),
        ([{"report": {"path": "../Other.Report"}}], "points outside"),
    ],
)
def test_pbip_file_with_bad_report_path(
    tmp_path: Path, artifacts: list[object], message: str
) -> None:
    pbip = tmp_path / "Sales.pbip"
    pbip.write_text(json.dumps({"artifacts": artifacts}))

    with pytest.raises(ProjectNotFoundError, match=message):
        detect_input(pbip)
