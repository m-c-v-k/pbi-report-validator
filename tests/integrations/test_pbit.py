from pathlib import Path

import pytest

from pbi_report_validator.domain.raw import RawLegacyReport
from pbi_report_validator.integrations.archives import UnsafeArchiveError
from pbi_report_validator.integrations.files import (
    InvalidJsonError,
    MissingDefinitionError,
    load_project,
)
from tests.factories import FIXTURES
from tests.pbit import LAYOUT, MODEL, pbit_entries, write_pbit, write_zip

LEGACY = FIXTURES / "sales_v1_legacy"


def test_loads_the_layout_and_the_model_schema(tmp_path: Path) -> None:
    project = load_project(write_pbit(LEGACY, tmp_path / "Sales.pbit"))

    assert project.name == "Sales"
    assert isinstance(project.report, RawLegacyReport)
    assert project.report.layout.path == LAYOUT
    legacy = load_project(LEGACY).report
    assert isinstance(legacy, RawLegacyReport)
    assert project.report.layout.content == legacy.layout.content
    assert project.semantic_model is not None
    assert project.semantic_model.path == MODEL
    assert project.semantic_model.bim is not None
    assert project.semantic_model.bim.content["model"]["tables"]
    assert project.model_missing is None


def test_upper_case_extension_is_read(tmp_path: Path) -> None:
    project = load_project(write_pbit(LEGACY, tmp_path / "Sales.PBIT"))

    assert project.semantic_model is not None


def test_layout_with_a_byte_order_mark(tmp_path: Path) -> None:
    entries = pbit_entries(LEGACY)
    entries[LAYOUT] = "\ufeff".encode("utf-16-le") + entries[LAYOUT]

    project = load_project(write_zip(tmp_path / "Sales.pbit", entries))

    assert isinstance(project.report, RawLegacyReport)
    assert project.report.layout.error is None


def test_without_model_schema_measures_are_not_compared(tmp_path: Path) -> None:
    entries = pbit_entries(LEGACY)
    del entries[MODEL]

    project = load_project(write_zip(tmp_path / "Sales.pbit", entries))

    assert project.semantic_model is None
    assert project.model_missing == "Sales.pbit has no DataModelSchema"


def test_without_layout_is_an_error(tmp_path: Path) -> None:
    entries = pbit_entries(LEGACY)
    del entries[LAYOUT]
    entries["Report/definition/report.json"] = b"{}"

    with pytest.raises(MissingDefinitionError, match="no Report/Layout"):
        load_project(write_zip(tmp_path / "Sales.pbit", entries))


@pytest.mark.parametrize(
    "layout",
    ["{not json".encode("utf-16-le"), b"\x00", b"{}", "[]".encode("utf-16-le")],
    ids=["invalid json", "odd length", "utf-8", "not an object"],
)
def test_unreadable_layout_is_an_error(tmp_path: Path, layout: bytes) -> None:
    entries = {**pbit_entries(LEGACY), LAYOUT: layout}

    with pytest.raises(InvalidJsonError, match=r"Sales\.pbit/Report/Layout"):
        load_project(write_zip(tmp_path / "Sales.pbit", entries))


def test_unreadable_model_schema_becomes_a_parse_issue(tmp_path: Path) -> None:
    entries = {**pbit_entries(LEGACY), MODEL: "{".encode("utf-16-le")}

    project = load_project(write_zip(tmp_path / "Sales.pbit", entries))

    assert project.semantic_model is not None
    assert project.semantic_model.bim is not None
    assert project.semantic_model.bim.error is not None


def test_path_escaping_archive_is_an_error(tmp_path: Path) -> None:
    entries = {**pbit_entries(LEGACY), "../outside": b""}

    with pytest.raises(UnsafeArchiveError):
        load_project(write_zip(tmp_path / "Sales.pbit", entries))
