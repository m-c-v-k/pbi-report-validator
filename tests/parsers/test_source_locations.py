import json
from pathlib import Path
from typing import Any

import pytest

from pbi_report_validator.domain.helpers import json_pointer, tmdl_reference
from pbi_report_validator.domain.models import (
    FieldKind,
    FieldRef,
    Projection,
    SourceLocation,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report, parse_visual
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from tests.factories import FIXTURES, fixture_report

FIXTURE_NAMES = ["sales_v1", "sales_v2", "sales_v3"]
OVERVIEW = "Sales.Report/definition/pages/overview"


def resolve(project: Path, location: SourceLocation) -> Any:
    """The JSON value a location points at (RFC 6901)."""
    node: Any = json.loads((project / location.file).read_text(encoding="utf-8-sig"))
    for part in location.pointer.split("/")[1:]:
        key = part.replace("~1", "/").replace("~0", "~")
        node = node[int(key)] if isinstance(node, list) else node[key]
    return node


@pytest.mark.parametrize("fixture", FIXTURE_NAMES)
def test_every_pbir_location_points_at_its_object(fixture: str) -> None:
    project = FIXTURES / fixture
    report = fixture_report(fixture)
    filters = [*report.filters, *(f for p in report.pages for f in p.filters)]
    for page in report.pages:
        assert page.location is not None
        assert resolve(project, page.location)["name"] == page.name
        for visual in page.visuals:
            assert visual.location is not None
            assert resolve(project, visual.location)["name"] == visual.name
            filters += visual.filters
            for projection in visual.projections:
                assert projection.location is not None
                assert "field" in resolve(project, projection.location)
            if visual.slicer and visual.slicer.condition:
                assert visual.slicer.location is not None
                assert "filter" in resolve(project, visual.slicer.location)
    assert filters
    for item in filters:
        assert item.location is not None
        assert resolve(project, item.location)["name"] == item.name


def test_fixture_locations() -> None:
    report = fixture_report("sales_v1")
    overview = report.pages[0]
    chart = next(v for v in overview.visuals if v.name == "chart_sales_by_month")
    slicer = next(v for v in overview.visuals if v.slicer)

    assert report.filters[0].location == SourceLocation(
        file="Sales.Report/definition/report.json", pointer="/filterConfig/filters/0"
    )
    assert overview.location == SourceLocation(file=f"{OVERVIEW}/page.json", pointer="")
    assert chart.location == SourceLocation(
        file=f"{OVERVIEW}/visuals/chart_sales_by_month/visual.json", pointer=""
    )
    assert [p.location.pointer for p in chart.projections if p.location] == [
        "/visual/query/queryState/Category/projections/0",
        "/visual/query/queryState/Y/projections/0",
    ]
    assert slicer.slicer is not None and slicer.slicer.location is not None
    assert slicer.slicer.location.pointer == (
        "/visual/objects/general/0/properties/filter"
    )


def test_measure_locations_name_the_file_and_object() -> None:
    raw = load_project(FIXTURES / "sales_v1").semantic_model
    assert raw is not None
    model = parse_semantic_model(raw)

    measures = [m for t in model.tables for m in t.measures]

    assert measures[0].location == SourceLocation(
        file="Sales.SemanticModel/definition/tables/Sales.tmdl",
        pointer="table Sales / measure 'Total Sales'",
    )
    assert all(m.location is not None for m in measures)


def test_slicer_without_selection_points_at_the_visual() -> None:
    body = {"visualType": "slicer"}
    content = {"name": "s", "position": {"x": 0, "y": 0, "width": 1, "height": 1}}

    visual, _ = parse_visual({**content, "visual": body}, "v/visual.json")

    assert visual.slicer is not None
    assert visual.slicer.location == SourceLocation(
        file="v/visual.json", pointer="/visual"
    )


def test_location_is_left_out_of_equality_hash_and_json() -> None:
    field = FieldRef(table="Sales", name="Amount", kind=FieldKind.COLUMN)
    here = SourceLocation(file="a/visual.json", pointer="/x")
    there = SourceLocation(file="b/visual.json", pointer="/y")
    first = Projection(role="Values", field=field, location=here)
    second = Projection(role="Values", field=field, location=there)

    assert first == second
    assert hash(first) == hash(second)
    assert "location" not in first.model_dump()
    assert first != Projection(role="Rows", field=field, location=here)


def test_reports_read_from_another_folder_are_equal() -> None:
    raw = load_project(FIXTURES / "sales_v1").report
    moved = raw.model_copy(
        update={
            "pages": tuple(
                page.model_copy(
                    update={
                        "page": page.page.model_copy(
                            update={"path": f"elsewhere/{page.page.path}"}
                        )
                    }
                )
                for page in raw.pages
            )
        }
    )

    original, copy = parse_report(raw), parse_report(moved)

    assert original.pages[0].location != copy.pages[0].location
    assert original == copy


@pytest.mark.parametrize(
    ("parts", "pointer"),
    [
        ((), ""),
        (("filterConfig", "filters", 0), "/filterConfig/filters/0"),
        (("a/b", "c~d"), "/a~1b/c~0d"),
    ],
)
def test_json_pointer_escapes_per_rfc_6901(
    parts: tuple[str | int, ...], pointer: str
) -> None:
    assert json_pointer(*parts) == pointer


@pytest.mark.parametrize(
    ("table", "measure", "reference"),
    [
        ("Sales", "Total", "table Sales / measure Total"),
        ("Online Sales", "Margin %", "table 'Online Sales' / measure 'Margin %'"),
        ("Sales", "Bob's", "table Sales / measure 'Bob''s'"),
    ],
)
def test_tmdl_reference_quotes_names_like_tmdl(
    table: str, measure: str, reference: str
) -> None:
    assert tmdl_reference(table, measure) == reference
