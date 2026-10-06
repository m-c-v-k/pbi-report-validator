from pathlib import Path
from typing import Any

import pytest

from pbi_report_validator.domain.models import FieldKind, FieldRef, FilterLevel
from pbi_report_validator.domain.raw import RawJsonFile, RawReport
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.pbir_filters import (
    UnsupportedConditionError,
    parse_filters,
    parse_slicer_state,
    render_condition,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
YEAR = FieldRef(table="Date", name="Year", kind=FieldKind.COLUMN)


def col(alias: str, name: str) -> dict[str, Any]:
    return {
        "Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": name}
    }


def lit(value: str) -> dict[str, Any]:
    return {"Literal": {"Value": value}}


def query(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "Version": 2,
        "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
        "Where": [{"Condition": c} for c in conditions],
    }


def test_sales_v1_filters_at_every_level() -> None:
    report = parse_report(load_project(FIXTURES / "sales_v1").report)

    assert report.issues == ()
    assert [(f.name, f.level, f.condition) for f in report.filters] == [
        ("report_filter_year", FilterLevel.REPORT, "Date[Year] in (2024, 2025)"),
    ]
    overview, details = report.pages
    assert [f.condition for f in overview.filters] == [
        "not (Product[Category] in ('Accessories'))"
    ]
    table = next(v for v in details.visuals if v.name == "table_product_sales")
    assert [(f.level, f.field, f.condition) for f in table.filters] == [
        (
            FilterLevel.VISUAL,
            FieldRef(table="Product", name="Category", kind=FieldKind.COLUMN),
            "Product[Category] in ('Bikes', 'Clothing')",
        )
    ]
    slicer = next(v for v in overview.visuals if v.name == "slicer_year")
    assert slicer.slicer is not None
    assert slicer.slicer.field == YEAR
    assert slicer.slicer.condition == "Date[Year] in (2025)"


def test_sales_v2_removed_filter_and_changed_slicer() -> None:
    report = parse_report(load_project(FIXTURES / "sales_v2").report)

    overview, details = report.pages[0], report.pages[1]
    table = next(v for v in details.visuals if v.name == "table_product_sales")
    slicer = next(v for v in overview.visuals if v.name == "slicer_year")
    assert table.filters == ()
    assert slicer.slicer is not None
    assert slicer.slicer.condition == "Date[Year] in (2024)"


def test_non_slicer_visuals_have_no_slicer_state() -> None:
    assert parse_slicer_state({"visualType": "card"}, None, []) is None


def test_slicer_without_selection_has_no_condition() -> None:
    state = parse_slicer_state({"visualType": "slicer"}, YEAR, [])

    assert state is not None
    assert (state.field, state.condition) == (YEAR, None)


@pytest.mark.parametrize(
    ("kind", "operator"), [(0, "="), (1, ">"), (2, ">="), (3, "<"), (4, "<=")]
)
def test_comparison(kind: int, operator: str) -> None:
    condition = {
        "Comparison": {
            "ComparisonKind": kind,
            "Left": col("s", "Amount"),
            "Right": lit("100D"),
        }
    }

    assert render_condition(query(condition)) == f"Sales[Amount] {operator} 100"


def test_and_or_and_multiple_where_items() -> None:
    gt = {
        "Comparison": {"ComparisonKind": 1, "Left": col("s", "A"), "Right": lit("1L")}
    }
    lt = {
        "Comparison": {"ComparisonKind": 3, "Left": col("s", "A"), "Right": lit("9L")}
    }
    either = {"Or": {"Left": gt, "Right": lt}}

    rendered = render_condition(query({"And": {"Left": gt, "Right": lt}}, either))

    assert rendered == (
        "((Sales[A] > 1) and (Sales[A] < 9)) and ((Sales[A] > 1) or (Sales[A] < 9))"
    )


def test_multi_column_in() -> None:
    condition = {
        "In": {
            "Expressions": [col("s", "Region"), col("s", "Year")],
            "Values": [[lit("'North'"), lit("2025L")], [lit("'South'"), lit("2024L")]],
        }
    }

    assert render_condition(query(condition)) == (
        "(Sales[Region], Sales[Year]) in (('North', 2025), ('South', 2024))"
    )


def test_non_numeric_suffix_is_kept() -> None:
    condition = {"In": {"Expressions": [col("s", "Code")], "Values": [[lit("'ABCL'")]]}}

    assert render_condition(query(condition)) == "Sales[Code] in ('ABCL')"


@pytest.mark.parametrize("value", [None, {}, {"Where": []}, {"Where": "x"}])
def test_no_where_gives_no_condition(value: Any) -> None:
    assert render_condition(value) is None


@pytest.mark.parametrize(
    "condition",
    [
        {"Between": {}},
        {"In": "x"},
        {"Comparison": {"ComparisonKind": 9, "Left": col("s", "A"), "Right": lit("1")}},
        {"Comparison": {"ComparisonKind": [], "Left": col("s", "A")}},
        {"In": {"Expressions": [col("zz", "A")], "Values": [[lit("1")]]}},
        {"In": {"Expressions": [col("s", "A")], "Values": [[{"Parameter": {}}]]}},
        {"And": {"Left": None, "Right": None}},
    ],
)
def test_unsupported_conditions_raise(condition: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedConditionError):
        render_condition(query(condition))


def test_unsupported_filter_is_kept_without_condition() -> None:
    container = {
        "filterConfig": {
            "filters": [
                {"name": "adv", "type": "Advanced", "filter": query({"Between": {}})},
                "not a filter",
            ]
        }
    }
    problems: list[str] = []

    filters = parse_filters(container, FilterLevel.PAGE, problems)

    assert [(f.name, f.filter_type, f.condition) for f in filters] == [
        ("adv", "Advanced", None)
    ]
    assert problems == ["filter adv: unsupported condition (Between)"]


@pytest.mark.parametrize(
    "container", [None, {}, {"filterConfig": []}, {"filterConfig": {"filters": {}}}]
)
def test_missing_filter_config_gives_no_filters(container: Any) -> None:
    assert parse_filters(container, FilterLevel.REPORT, []) == ()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12L", "12"),
        ("-3.5D", "-3.5"),
        ("infD", "infD"),
        ("nanL", "nanL"),
        ("1_0L", "1_0L"),
        ("null", "null"),
        ("true", "true"),
        ("datetime'2025-01-01T00:00:00'", "datetime'2025-01-01T00:00:00'"),
    ],
)
def test_literal_rendering(value: str, expected: str) -> None:
    condition = {"In": {"Expressions": [col("s", "A")], "Values": [[lit(value)]]}}

    assert render_condition(query(condition)) == f"Sales[A] in ({expected})"


def test_not_combined_with_and_is_unambiguous() -> None:
    a_in = {"In": {"Expressions": [col("s", "A")], "Values": [[lit("1L")]]}}
    b_in = {"In": {"Expressions": [col("s", "B")], "Values": [[lit("2L")]]}}

    rendered = render_condition(
        query({"Not": {"Expression": {"And": {"Left": a_in, "Right": b_in}}}}, a_in)
    )

    assert (
        rendered == "not ((Sales[A] in (1)) and (Sales[B] in (2))) and Sales[A] in (1)"
    )


def test_slicer_with_no_projection_has_no_field() -> None:
    body = {
        "visualType": "slicer",
        "objects": {
            "general": [
                {
                    "properties": {
                        "filter": {
                            "filter": query(
                                {
                                    "In": {
                                        "Expressions": [col("s", "Year")],
                                        "Values": [[lit("1L")]],
                                    }
                                }
                            )
                        }
                    }
                }
            ]
        },
    }

    state = parse_slicer_state(body, None, [])

    assert state is not None
    assert (state.field, state.condition) == (None, "Sales[Year] in (1)")


def test_report_filter_problem_becomes_issue_with_path() -> None:
    raw = RawReport(
        path="Sales.Report",
        report=RawJsonFile(
            path="Sales.Report/definition/report.json",
            content={
                "filterConfig": {
                    "filters": [{"name": "f", "filter": query({"Between": {}})}]
                }
            },
        ),
    )

    report = parse_report(raw)

    assert report.filters[0].condition is None
    assert [(i.path, i.message) for i in report.issues] == [
        (
            "Sales.Report/definition/report.json",
            "filter f: unsupported condition (Between)",
        )
    ]
