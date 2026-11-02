"""Filters the parser cannot read, in the shapes Power BI Desktop saves them."""

import json
from typing import Any

import pytest

from pbi_report_validator.dax.builder import build_query
from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.diff.severity import default_severity
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    Report,
    ReportMatch,
    Severity,
    SlicerState,
    UnsupportedQuery,
)
from pbi_report_validator.matching.matcher import match_reports
from pbi_report_validator.parsers.pbir_filters import (
    parse_filters,
    parse_slicer_state,
)
from tests import factories

AMOUNT = FieldRef(table="Sales", name="Amount", kind=FieldKind.COLUMN)


def col(name: str, alias: str = "s") -> dict[str, Any]:
    return {
        "Column": {"Expression": {"SourceRef": {"Source": alias}}, "Property": name}
    }


def entity(name: str) -> dict[str, Any]:
    return {
        "Column": {"Expression": {"SourceRef": {"Entity": "Sales"}}, "Property": name}
    }


def relative_days(days: int, alias: str = "s") -> dict[str, Any]:
    day_after = {"DateAdd": {"Expression": {"Now": {}}, "Amount": 1, "TimeUnit": 0}}
    start = {"DateAdd": {"Expression": day_after, "Amount": -days, "TimeUnit": 0}}
    between = {
        "Expression": col("Date", alias),
        "LowerBound": {"DateSpan": {"Expression": start, "TimeUnit": 0}},
        "UpperBound": {"DateSpan": {"Expression": {"Now": {}}, "TimeUnit": 0}},
    }
    return {
        "Version": 2,
        "From": [{"Name": alias, "Entity": "Sales", "Type": 0}],
        "Where": [{"Condition": {"Between": between}}],
    }


def contains(text: str) -> dict[str, Any]:
    body = {"Left": col("Category"), "Right": {"Literal": {"Value": f"'{text}'"}}}
    return {
        "Version": 2,
        "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
        "Where": [{"Condition": {"Contains": body}}],
    }


def bikes() -> dict[str, Any]:
    body = {
        "Expressions": [col("Category")],
        "Values": [[{"Literal": {"Value": "'Bikes'"}}]],
    }
    return {
        "Version": 2,
        "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
        "Where": [{"Condition": {"In": body}}],
    }


def card(
    query: dict[str, Any] | None,
    filter_type: str = "Advanced",
    field: str = "Category",
) -> dict[str, Any]:
    entry = {"name": "f", "type": filter_type, "field": entity(field)}
    return entry if query is None else {**entry, "filter": query}


def report(entry: dict[str, Any]) -> Report:
    container = {"filterConfig": {"filters": [entry]}}
    filters, _ = parse_filters(container, FilterLevel.REPORT)
    return Report(filters=filters)


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[Any]:
    findings = diff_content(report(old), report(new), ReportMatch(), {})
    return [(f.change, f.severity, f.old, f.new) for f in findings]


def only_filter(entry: dict[str, Any]) -> Filter:
    return report(entry).filters[0]


def test_unread_filter_keeps_its_definition() -> None:
    parsed = only_filter(card(relative_days(7), "RelativeDate", "Date"))

    assert parsed.condition is None
    assert parsed.unread is not None
    assert '"Amount": -7' in parsed.unread


def test_empty_card_and_parsed_filter_have_nothing_unread() -> None:
    assert only_filter(card(None)).unread is None
    assert only_filter(card(bikes())).unread is None


def test_changed_relative_date_is_a_finding() -> None:
    old = only_filter(card(relative_days(7), "RelativeDate", "Date"))
    new = only_filter(card(relative_days(30), "RelativeDate", "Date"))

    assert diff(
        card(relative_days(7), "RelativeDate", "Date"),
        card(relative_days(30), "RelativeDate", "Date"),
    ) == [(ChangeKind.MODIFIED, Severity.CRITICAL, old.unread, new.unread)]


def test_alias_names_do_not_count_as_a_change() -> None:
    assert (
        diff(
            card(relative_days(7, alias="s"), "RelativeDate", "Date"),
            card(relative_days(7, alias="d"), "RelativeDate", "Date"),
        )
        == []
    )


def test_unread_definition_keeps_the_subquery_settings() -> None:
    subquery = {"Top": 5, "From": [{"Name": "t", "Entity": "Sales", "Type": 0}]}
    query = {
        "From": [
            {"Name": "sub", "Expression": {"Subquery": {"Query": subquery}}},
            {"Name": "s", "Entity": "Sales", "Type": 0},
        ],
        "Where": [
            {
                "Condition": {
                    "In": {
                        "Expressions": [col("Category")],
                        "Table": {"SourceRef": {"Source": "sub"}},
                    }
                }
            }
        ],
    }

    unread = only_filter(card(query)).unread

    assert unread is not None
    source = json.loads(unread)[0]["Condition"]["In"]["Table"]["SourceRef"]
    assert source == {"Subquery": {"Top": 5}}


def test_parsed_to_unread_shows_the_new_definition() -> None:
    new = only_filter(card(contains("Cloth")))

    assert diff(card(bikes(), "Categorical"), card(contains("Cloth"))) == [
        (
            ChangeKind.MODIFIED,
            Severity.CRITICAL,
            "Sales[Category] in ('Bikes')",
            new.unread,
        )
    ]
    assert new.unread is not None
    assert "Cloth" in new.unread


def test_changed_field_is_a_finding_even_without_a_condition() -> None:
    assert diff(card(None, field="Category"), card(None, field="Region")) == [
        (
            ChangeKind.MODIFIED,
            Severity.CRITICAL,
            "Sales[Category]",
            "Sales[Region]",
        )
    ]


def test_changed_field_with_an_equal_condition_is_a_finding() -> None:
    old = card(bikes(), "Categorical", field="Category")
    new = card(bikes(), "Categorical", field="Region")

    assert diff(old, new) == [
        (ChangeKind.MODIFIED, Severity.CRITICAL, "Sales[Category]", "Sales[Region]")
    ]


def test_renamed_measure_inside_an_unread_filter_shows_as_a_change() -> None:
    def on_measure(name: str) -> dict[str, Any]:
        query = contains("x")
        measure = {"Expression": {"SourceRef": {"Source": "s"}}, "Property": name}
        query["Where"][0]["Condition"]["Contains"]["Left"] = {"Measure": measure}
        return card(query)

    renames = {"Sales[Margin]": "Sales[Gross Margin]"}
    findings = diff_content(
        report(on_measure("Margin")),
        report(on_measure("Gross Margin")),
        ReportMatch(),
        renames,
    )

    assert [f.change for f in findings] == [ChangeKind.MODIFIED]


def test_renamed_measure_field_is_not_a_field_change() -> None:
    old = report(card(None, field="Margin"))
    new = report(card(None, field="Gross Margin"))

    renames = {"Sales[Margin]": "Sales[Gross Margin]"}

    assert diff_content(old, new, ReportMatch(), renames) == []


def test_type_only_change_is_info() -> None:
    assert diff(card(bikes(), "Categorical"), card(bikes(), "Advanced")) == [
        (ChangeKind.RETYPED, Severity.INFO, "Categorical", "Advanced")
    ]
    assert default_severity(Category.FILTER, ChangeKind.RETYPED) is Severity.INFO


def test_unchanged_filters_give_no_finding() -> None:
    assert diff(card(contains("Cloth")), card(contains("Cloth"))) == []
    assert diff(card(None), card(None)) == []


def slicer_body(query: dict[str, Any]) -> dict[str, Any]:
    general = [{"properties": {"filter": {"filter": query}}}]
    return {"visualType": "slicer", "objects": {"general": general}}


def test_unread_slicer_selection_is_compared() -> None:
    old, _ = parse_slicer_state(slicer_body(contains("Bike")), None)
    new, _ = parse_slicer_state(slicer_body(contains("Cloth")), None)
    assert old is not None
    assert new is not None
    assert old.condition is None
    old_report = factories.report(
        factories.page("p", factories.visual("v", "slicer", slicer=old))
    )
    new_report = factories.report(
        factories.page("p", factories.visual("v", "slicer", slicer=new))
    )

    match = match_reports(old_report.pages, new_report.pages)
    findings = diff_content(old_report, new_report, match, {})

    assert [(f.category, f.old, f.new) for f in findings] == [
        (Category.SLICER, old.unread, new.unread)
    ]


def test_visual_with_an_unread_filter_is_not_queried() -> None:
    unread = only_filter(card(relative_days(7), "RelativeDate", "Date"))
    visual = factories.visual(
        "v", "tableEx", fields=(AMOUNT,), filters=(unread,), width=10, height=10
    )

    result = build_query(visual, factories.page("p", visual), [])

    assert result == UnsupportedQuery(reason="filter f could not be read")


def test_report_level_unread_filter_stops_the_query() -> None:
    unread = only_filter(card(contains("Cloth")))
    visual = factories.visual("v", "tableEx", fields=(AMOUNT,), width=10, height=10)

    result = build_query(visual, factories.page("p", visual), [unread])

    assert isinstance(result, UnsupportedQuery)


def test_unread_slicer_stops_queries_of_the_other_visuals() -> None:
    slicer = factories.visual(
        "s", "slicer", slicer=SlicerState(unread="[]"), width=10, height=10
    )
    visual = factories.visual("v", "tableEx", fields=(AMOUNT,), width=10, height=10)

    result = build_query(visual, factories.page("p", visual, slicer), [])

    assert result == UnsupportedQuery(reason="slicer s could not be read")


def test_empty_card_does_not_stop_the_query() -> None:
    empty = only_filter(card(None))
    visual = factories.visual(
        "v", "tableEx", fields=(AMOUNT,), filters=(empty,), width=10, height=10
    )

    result = build_query(visual, factories.page("p", visual), [])

    assert not isinstance(result, UnsupportedQuery)


@pytest.mark.parametrize("days", [7, 30])
def test_relative_date_gives_one_parse_problem(days: int) -> None:
    entry = card(relative_days(days), "RelativeDate", "Date")
    container = {"filterConfig": {"filters": [entry]}}

    _, problems = parse_filters(container, FilterLevel.PAGE)

    assert problems == ["filter f: unsupported condition (Between)"]
