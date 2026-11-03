from typing import Any

import pytest

from pbi_report_validator.domain.models import FieldKind, FieldRef
from pbi_report_validator.parsers.pbir_fields import parse_field, unknown_field


def entity(name: str) -> dict[str, Any]:
    return {"SourceRef": {"Entity": name}}


def column(table: str, name: str) -> dict[str, Any]:
    return {"Column": {"Expression": entity(table), "Property": name}}


def test_column() -> None:
    assert parse_field(column("Date", "Year")) == FieldRef(
        table="Date", name="Year", kind=FieldKind.COLUMN
    )


def test_measure() -> None:
    field = {"Measure": {"Expression": entity("Sales"), "Property": "Total Sales"}}

    assert parse_field(field) == FieldRef(
        table="Sales", name="Total Sales", kind=FieldKind.MEASURE
    )


@pytest.mark.parametrize(
    ("function", "expected"),
    [(0, "Sum"), (2, "DistinctCount"), (99, "99"), (None, None), (True, None)],
)
def test_aggregation(function: Any, expected: str | None) -> None:
    field = {
        "Aggregation": {"Expression": column("Sales", "Amount"), "Function": function}
    }

    assert parse_field(field) == FieldRef(
        table="Sales",
        name="Amount",
        kind=FieldKind.AGGREGATION,
        aggregation=expected,
    )


def test_hierarchy_level() -> None:
    field = {
        "HierarchyLevel": {
            "Expression": {
                "Hierarchy": {"Expression": entity("Date"), "Hierarchy": "Calendar"}
            },
            "Level": "Year",
        }
    }

    assert parse_field(field) == FieldRef(
        table="Date", name="Calendar.Year", kind=FieldKind.HIERARCHY_LEVEL
    )


def auto_date_level(column_name: str, level: str) -> dict[str, Any]:
    """An auto date/time level, as Power BI Desktop writes it."""
    variation = {
        "PropertyVariationSource": {
            "Expression": entity("Sales"),
            "Name": "Variation",
            "Property": column_name,
        }
    }
    return {
        "HierarchyLevel": {
            "Expression": {
                "Hierarchy": {"Expression": variation, "Hierarchy": "Date Hierarchy"}
            },
            "Level": level,
        }
    }


def test_auto_date_hierarchy_level() -> None:
    assert parse_field(auto_date_level("Order Date", "Month")) == FieldRef(
        table="Sales",
        name="Order Date.Date Hierarchy.Month",
        kind=FieldKind.HIERARCHY_LEVEL,
    )


def test_auto_date_levels_of_different_columns_differ() -> None:
    order = parse_field(auto_date_level("Order Date", "Year"))
    ship = parse_field(auto_date_level("Ship Date", "Year"))

    assert order is not None and ship is not None
    assert order.key != ship.key


def test_unknown_field_is_named_by_kind_and_content() -> None:
    calc = {"NativeVisualCalculation": {"Name": "Running", "Expression": "RUNNINGSUM"}}
    edited = {"NativeVisualCalculation": {"Name": "Running", "Expression": "SUM"}}

    field = unknown_field(calc)

    assert field is not None
    assert field.kind == FieldKind.UNKNOWN
    assert field.name.startswith("NativeVisualCalculation ")
    assert field == unknown_field(dict(reversed(list(calc.items()))))
    assert field != unknown_field(edited)


@pytest.mark.parametrize("expression", [None, "text", {}, []])
def test_unknown_field_needs_a_non_empty_object(expression: Any) -> None:
    assert unknown_field(expression) is None


def test_source_alias_is_resolved() -> None:
    field = {
        "Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "Year"}
    }

    assert parse_field(field, {"d": "Date"}) == FieldRef(
        table="Date", name="Year", kind=FieldKind.COLUMN
    )


def test_unknown_alias_gives_none() -> None:
    field = {
        "Column": {"Expression": {"SourceRef": {"Source": "x"}}, "Property": "Year"}
    }

    assert parse_field(field, {"d": "Date"}) is None


def test_aggregation_over_measure_is_an_aggregation() -> None:
    measure = {"Measure": {"Expression": entity("Sales"), "Property": "Total"}}
    field = {"Aggregation": {"Expression": measure, "Function": 3}}

    assert parse_field(field) == FieldRef(
        table="Sales", name="Total", kind=FieldKind.AGGREGATION, aggregation="Min"
    )


@pytest.mark.parametrize(
    "expression",
    [
        None,
        "Sales[Amount]",
        {"Unsupported": {}},
        {"Column": {"Property": "Year"}},
        {"Column": {"Expression": entity("Date")}},
        {"Column": {"Expression": {"SourceRef": {"Source": "x"}}, "Property": "Y"}},
        {"Aggregation": {"Expression": {"Unsupported": {}}, "Function": 0}},
        {"HierarchyLevel": {"Expression": {}, "Level": "Year"}},
        {"HierarchyLevel": {"Expression": None, "Level": "Year"}},
        {"HierarchyLevel": {"Expression": "Calendar", "Level": "Year"}},
        {"Measure": "Total"},
    ],
)
def test_unrecognised_expressions_give_none(expression: Any) -> None:
    assert parse_field(expression) is None
