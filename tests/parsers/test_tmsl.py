import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pbi_report_validator.domain.models import (
    Category,
    Column,
    Measure,
    SemanticModel,
    SourceLocation,
)
from pbi_report_validator.domain.raw import RawJsonFile
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from pbi_report_validator.parsers.tmsl import parse_bim
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES

BIM = "Sales.SemanticModel/model.bim"


def bim(*tables: dict[str, Any]) -> RawJsonFile:
    return RawJsonFile(path=BIM, content={"model": {"tables": list(tables)}})


def tmdl_model(fixture: str) -> SemanticModel:
    raw = load_project(FIXTURES / fixture).semantic_model
    assert raw is not None
    return parse_semantic_model(raw)


def as_bim(model: SemanticModel) -> dict[str, Any]:
    """The TMSL form of a model; expressions as lists of lines, as Desktop writes."""
    tables = [
        {
            "name": t.name,
            "columns": [{"name": c.name, "dataType": c.data_type} for c in t.columns],
            "measures": [
                {"name": m.name, "expression": m.expression.splitlines()}
                for m in t.measures
            ],
        }
        for t in model.tables
    ]
    return {"name": "Sales", "compatibilityLevel": 1567, "model": {"tables": tables}}


def saved_as_bim(tmp_path: Path, fixture: str) -> Path:
    """A copy of ``fixture`` whose semantic model is a ``model.bim``."""
    target = shutil.copytree(FIXTURES / fixture, tmp_path / fixture)
    model_dir = target / "Sales.SemanticModel"
    shutil.rmtree(model_dir / "definition")
    content = json.dumps(as_bim(tmdl_model(fixture)), indent=2)
    (model_dir / "model.bim").write_text(content, encoding="utf-8")
    return target


@pytest.mark.parametrize("fixture", ["sales_v1", "sales_v2"])
def test_bim_reads_the_same_tables_as_tmdl(tmp_path: Path, fixture: str) -> None:
    raw = load_project(saved_as_bim(tmp_path, fixture)).semantic_model
    assert raw is not None

    assert parse_semantic_model(raw) == tmdl_model(fixture)


def test_bim_pair_gives_the_same_measure_findings_as_tmdl(tmp_path: Path) -> None:
    old, new = saved_as_bim(tmp_path, "sales_v1"), saved_as_bim(tmp_path, "sales_v2")

    def measures(old_path: Path, new_path: Path) -> list[tuple[str, str, str]]:
        findings = validate(old_path, new_path).findings
        return [
            (f.change.value, f.path, f.message)
            for f in findings
            if f.category in (Category.MEASURE, Category.PARSE_ISSUE)
        ]

    expected = measures(FIXTURES / "sales_v1", FIXTURES / "sales_v2")
    assert expected
    assert measures(old, new) == expected


def test_string_and_list_expressions_and_locations() -> None:
    model = parse_bim(
        bim(
            {
                "name": "Sales",
                "columns": [{"name": "Amount", "dataType": "decimal"}],
                "measures": [
                    {"name": "Total", "expression": " SUM(Sales[Amount]) "},
                    {"name": "Margin", "expression": ["DIVIDE(", "  1, 2", ")"]},
                ],
            }
        )
    )

    (table,) = model.tables
    assert table.columns == (Column(name="Amount", data_type="decimal"),)
    assert [(m.name, m.expression) for m in table.measures] == [
        ("Total", "SUM(Sales[Amount])"),
        ("Margin", "DIVIDE(\n  1, 2\n)"),
    ]
    assert table.measures[1].location == SourceLocation(
        file=BIM, pointer="/model/tables/0/measures/1"
    )
    assert model.issues == ()


def test_measure_without_expression_is_a_parse_issue() -> None:
    measures = [
        {"name": "Empty"},
        {"expression": "1"},
        {"name": "Ok", "expression": "1"},
    ]

    model = parse_bim(bim({"name": "Sales", "measures": measures}))

    assert model.tables[0].measures == (Measure(name="Ok", expression="1"),)
    assert [(i.message, i.measure) for i in model.issues] == [
        ("measure Sales[Empty] has no name or expression", "Sales[Empty]"),
        ("measure Sales[#1] has no name or expression", "Sales[#1]"),
    ]


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (RawJsonFile(path=BIM, error="Expecting value"), "unreadable: Expecting value"),
        (RawJsonFile(path=BIM, content={}), "model.bim has no model.tables list"),
        (bim({"measures": []}), "table 0 has no name"),
    ],
)
def test_unreadable_bim_or_table_is_a_parse_issue(
    raw: RawJsonFile, message: str
) -> None:
    model = parse_bim(raw)

    assert [(i.path, i.message) for i in model.issues] == [(BIM, message)]
