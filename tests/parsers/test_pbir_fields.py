from typing import Any

import pytest

from pbi_report_validator.domain.models import FieldKind, FieldRef
from pbi_report_validator.parsers.pbir_fields import parse_field


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
    ("function", "expected"), [(0, "Sum"), (2, "DistinctCount"), (99, "99")]
)
def test_aggregation(function: int, expected: str) -> None:
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


def test_source_alias_is_resolved() -> None:
    field = {
        "Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "Year"}
    }

    assert parse_field(field, {"d": "Date"}) == FieldRef(
        table="Date", name="Year", kind=FieldKind.COLUMN
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
    ],
)
def test_unrecognised_expressions_give_none(expression: Any) -> None:
    assert parse_field(expression) is None
