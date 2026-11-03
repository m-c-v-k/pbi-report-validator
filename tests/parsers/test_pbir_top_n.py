"""TopN filters, in the shape Power BI Desktop saves them."""

from typing import Any

import pytest

from pbi_report_validator.dax.builder import build_query
from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    FieldKind,
    FieldRef,
    FilterLevel,
    InCondition,
    Report,
    ReportMatch,
    TopNCondition,
    UnsupportedQuery,
)
from pbi_report_validator.parsers.pbir_filters import (
    UnsupportedConditionError,
    parse_condition,
    parse_filters,
    render,
)
from tests import factories

COLUMN = FieldRef(table="Table", name="Column1", kind=FieldKind.COLUMN)
SUM = FieldRef(
    table="Table", name="Column1", kind=FieldKind.AGGREGATION, aggregation="Sum"
)


def column() -> dict[str, Any]:
    return {
        "Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": "Column1"}
    }


def top_n(top: Any = 5, direction: Any = 2) -> dict[str, Any]:
    subquery = {
        "Version": 2,
        "From": [{"Name": "t", "Entity": "Table", "Type": 0}],
        "Select": [{**column(), "Name": "field"}],
        "OrderBy": [
            {
                "Direction": direction,
                "Expression": {"Aggregation": {"Expression": column(), "Function": 0}},
            }
        ],
        "Top": top,
    }
    table_in = {
        "Expressions": [column()],
        "Table": {"SourceRef": {"Source": "subquery"}},
    }
    return {
        "Version": 2,
        "From": [
            {
                "Name": "subquery",
                "Expression": {"Subquery": {"Query": subquery}},
                "Type": 2,
            },
            {"Name": "t", "Entity": "Table", "Type": 0},
        ],
        "Where": [{"Condition": {"In": table_in}}],
    }


def report(filter_query: dict[str, Any]) -> Report:
    entry = {"name": "top", "type": "TopN", "filter": filter_query}
    container = {"filterConfig": {"filters": [entry]}}
    filters, problems = parse_filters(container, FilterLevel.REPORT)
    assert problems == []
    return Report(filters=filters)


def test_top_n_keeps_count_direction_and_order() -> None:
    assert parse_condition(top_n()) == TopNCondition(
        field=COLUMN, direction="top", count=5, order_by=SUM
    )


@pytest.mark.parametrize(
    ("direction", "expected"),
    [
        (2, "Table[Column1] top 5 by Sum(Table[Column1])"),
        (1, "Table[Column1] bottom 5 by Sum(Table[Column1])"),
    ],
)
def test_top_n_renders_its_settings(direction: int, expected: str) -> None:
    condition = parse_condition(top_n(direction=direction))
    assert condition is not None
    assert render(condition) == expected


def test_changed_top_n_count_is_a_filter_finding() -> None:
    findings = diff_content(report(top_n(5)), report(top_n(10)), ReportMatch(), {})

    assert [(f.category, f.change, f.old, f.new) for f in findings] == [
        (
            Category.FILTER,
            ChangeKind.MODIFIED,
            "Table[Column1] top 5 by Sum(Table[Column1])",
            "Table[Column1] top 10 by Sum(Table[Column1])",
        )
    ]


@pytest.mark.parametrize(
    "broken",
    [
        top_n(top=0),
        top_n(top="5"),
        top_n(top=True),
        top_n(direction=3),
        top_n(direction={}),
        {**top_n(), "From": [{"Name": "t", "Entity": "Table", "Type": 0}]},
    ],
)
def test_unknown_subquery_form_is_unsupported(broken: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedConditionError):
        parse_condition(broken)


def test_in_without_values_or_table_is_unsupported() -> None:
    query = top_n()
    in_body = query["Where"][0]["Condition"]["In"]
    del in_body["Table"]

    with pytest.raises(UnsupportedConditionError):
        parse_condition(query)


def query_with(condition: TopNCondition | InCondition) -> Any:
    card = factories.filter_card(condition, filter_type="TopN")
    visual = factories.visual(
        "v", "tableEx", fields=(COLUMN,), filters=(card,), width=10, height=10
    )
    return build_query(visual, factories.page("p", visual), [])


def test_visual_with_a_top_n_filter_is_not_queried() -> None:
    condition = parse_condition(top_n())
    assert isinstance(condition, TopNCondition)

    assert query_with(condition) == UnsupportedQuery(
        reason="TopN filters are not supported yet"
    )


def test_in_without_rows_never_reaches_dax() -> None:
    result = query_with(InCondition(fields=(COLUMN,), rows=()))

    assert result == UnsupportedQuery(reason="filters without values are not supported")
