from pathlib import Path
from typing import Any

import pytest

from pbi_report_validator.domain.models import (
    AllCondition,
    BinaryCondition,
    ComparisonCondition,
    FieldKind,
    FieldRef,
    Filter,
    InCondition,
    LiteralKind,
    LiteralValue,
    NotCondition,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.pbir_filters import (
    parse_condition,
    parse_literal,
    render,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
AMOUNT = FieldRef(table="Sales", name="Amount", kind=FieldKind.COLUMN)


def col(name: str) -> dict[str, Any]:
    return {"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": name}}


def lit(value: str) -> dict[str, Any]:
    return {"Literal": {"Value": value}}


def query(*conditions: dict[str, Any]) -> dict[str, Any]:
    return {
        "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
        "Where": [{"Condition": c} for c in conditions],
    }


def all_filters(name: str) -> list[Filter]:
    report = parse_report(load_project(FIXTURES / name).report)
    filters = list(report.filters)
    for page in report.pages:
        filters += page.filters
        for visual in page.visuals:
            filters += visual.filters
    return filters


@pytest.mark.parametrize("fixture", ["sales_v1", "sales_v2"])
def test_fixture_conditions_match_their_structured_form(fixture: str) -> None:
    report = parse_report(load_project(FIXTURES / fixture).report)
    slicers = [v.slicer for p in report.pages for v in p.visuals if v.slicer]

    for item in [*all_filters(fixture), *slicers]:
        assert item.expression is not None
        assert render(item.expression) == item.condition


def test_fixture_slicer_expression() -> None:
    report = parse_report(load_project(FIXTURES / "sales_v1").report)
    slicer = next(v.slicer for v in report.pages[0].visuals if v.slicer)

    assert slicer.expression == InCondition(
        fields=(FieldRef(table="Date", name="Year", kind=FieldKind.COLUMN),),
        rows=((LiteralValue(kind=LiteralKind.NUMBER, value="2025"),),),
    )


@pytest.mark.parametrize(
    ("raw", "kind", "value"),
    [
        ("2025L", LiteralKind.NUMBER, "2025"),
        ("-3.5D", LiteralKind.NUMBER, "-3.5"),
        ("7", LiteralKind.NUMBER, "7"),
        ("'Bob''s'", LiteralKind.TEXT, "Bob's"),
        ("true", LiteralKind.BOOLEAN, "true"),
        ("null", LiteralKind.NULL, ""),
        ("datetime'2025-01-01T00:00:00'", LiteralKind.DATETIME, "2025-01-01T00:00:00"),
        ("infD", LiteralKind.OTHER, "infD"),
    ],
)
def test_literal_kinds(raw: str, kind: LiteralKind, value: str) -> None:
    assert parse_literal(raw) == LiteralValue(kind=kind, value=value)


def test_comparison_not_and_or() -> None:
    gt = {
        "Comparison": {"ComparisonKind": 1, "Left": col("Amount"), "Right": lit("1L")}
    }
    lt = {
        "Comparison": {"ComparisonKind": 3, "Left": col("Amount"), "Right": lit("9L")}
    }

    parsed = parse_condition(
        query({"Not": {"Expression": {"Or": {"Left": gt, "Right": lt}}}})
    )

    one = LiteralValue(kind=LiteralKind.NUMBER, value="1")
    nine = LiteralValue(kind=LiteralKind.NUMBER, value="9")
    assert parsed == NotCondition(
        operand=BinaryCondition(
            kind="or",
            left=ComparisonCondition(field=AMOUNT, operator=">", value=one),
            right=ComparisonCondition(field=AMOUNT, operator="<", value=nine),
        )
    )


def test_several_where_items_become_all_condition() -> None:
    a = {"In": {"Expressions": [col("A")], "Values": [[lit("1L")]]}}
    b = {"In": {"Expressions": [col("B")], "Values": [[lit("'x'")]]}}

    parsed = parse_condition(query(a, b))

    assert isinstance(parsed, AllCondition)
    assert len(parsed.items) == 2
    assert render(parsed) == "Sales[A] in (1) and Sales[B] in ('x')"


def test_structured_conditions_round_trip_through_json() -> None:
    a = {
        "In": {
            "Expressions": [col("A"), col("B")],
            "Values": [[lit("1L"), lit("null")]],
        }
    }
    gt = {"Comparison": {"ComparisonKind": 2, "Left": col("A"), "Right": lit("true")}}

    parsed = parse_condition(query({"And": {"Left": a, "Right": gt}}, a))

    assert parsed is not None
    restored = type(parsed).model_validate_json(parsed.model_dump_json())
    assert restored == parsed


def test_unsupported_filter_has_neither_condition_nor_expression() -> None:
    from pbi_report_validator.domain.models import FilterLevel
    from pbi_report_validator.parsers.pbir_filters import parse_filters

    container = {
        "filterConfig": {"filters": [{"name": "f", "filter": query({"Between": {}})}]}
    }

    (parsed,) = parse_filters(container, FilterLevel.PAGE, [])

    assert (parsed.condition, parsed.expression) == (None, None)
