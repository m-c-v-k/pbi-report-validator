from pathlib import Path

import pytest

from pbi_report_validator.dax.builder import build_query, column, literal, text
from pbi_report_validator.domain.models import (
    AllCondition,
    BinaryCondition,
    ComparisonCondition,
    Condition,
    DaxQuery,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    InCondition,
    LiteralKind,
    LiteralValue,
    NotCondition,
    Page,
    Position,
    Projection,
    SlicerState,
    UnsupportedQuery,
    Visual,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report

FIXTURES = Path(__file__).parent.parent / "fixtures"
SNAPSHOT = Path(__file__).parent.parent / "snapshots" / "dax_sales.txt"
POS = Position(x=0, y=0, width=10, height=10)
YEAR = FieldRef(table="Date", name="Year", kind=FieldKind.COLUMN)
REGION = FieldRef(table="Sales", name="Region", kind=FieldKind.COLUMN)
TOTAL = FieldRef(table="Sales", name="Total Sales", kind=FieldKind.MEASURE)


def num(value: str) -> LiteralValue:
    return LiteralValue(kind=LiteralKind.NUMBER, value=value)


def visual(
    *fields: FieldRef, visual_type: str = "tableEx", filters: tuple[Filter, ...] = ()
) -> Visual:
    return Visual(
        name="v",
        visual_type=visual_type,
        position=POS,
        projections=tuple(Projection(role="Values", field=f) for f in fields),
        filters=filters,
    )


def page(*visuals: Visual, filters: tuple[Filter, ...] = ()) -> Page:
    return Page(
        name="p",
        display_name="P",
        ordinal=0,
        width=100,
        height=100,
        visuals=visuals,
        filters=filters,
    )


def flt(expression: Condition) -> Filter:
    return Filter(
        name="f",
        level=FilterLevel.VISUAL,
        filter_type="Advanced",
        expression=expression,
    )


def query_for(
    v: Visual, *extra_visuals: Visual, page_filters: tuple[Filter, ...] = ()
) -> DaxQuery | UnsupportedQuery:
    return build_query(v, page(v, *extra_visuals, filters=page_filters), [])


def dax(v: Visual, **kwargs: tuple[Filter, ...]) -> str:
    result = query_for(v, **kwargs)
    assert isinstance(result, DaxQuery), result
    return result.dax


def fixture_queries() -> str:
    blocks = []
    for name in ("sales_v1", "sales_v2"):
        report = parse_report(load_project(FIXTURES / name).report)
        for p in report.pages:
            for v in p.visuals:
                result = build_query(v, p, report.filters)
                body = (
                    result.dax
                    if isinstance(result, DaxQuery)
                    else f"-- unsupported: {result.reason}"
                )
                blocks.append(f"-- {name} {p.name}/{v.name}\n{body}\n")
    return "\n".join(blocks)


def test_fixture_queries_match_snapshot() -> None:
    # After an intended change, regenerate the snapshot with:
    # uv run python -c "from tests.dax.test_builder import fixture_queries as f; \
    #   open('tests/snapshots/dax_sales.txt', 'w', newline='\n').write(f())"
    assert fixture_queries() == SNAPSHOT.read_text(encoding="utf-8")


def test_renamed_measure_uses_new_name_in_new_version() -> None:
    queries = fixture_queries()
    v2 = queries[queries.index("-- sales_v2") :]

    assert '"Gross Margin %", [Gross Margin %]' in v2
    assert "[Margin %]" not in v2


def test_card_has_no_group_by_and_no_order_by() -> None:
    result = query_for(visual(TOTAL, visual_type="card"))

    assert isinstance(result, DaxQuery)
    assert result.group_by == ()
    assert result.values == ("Total Sales",)
    assert (
        result.dax == 'EVALUATE\nSUMMARIZECOLUMNS(\n    "Total Sales", [Total Sales]\n)'
    )


def test_table_groups_by_columns_and_orders() -> None:
    result = query_for(visual(REGION, TOTAL))

    assert isinstance(result, DaxQuery)
    assert result.group_by == ("'Sales'[Region]",)
    assert result.dax.endswith("ORDER BY 'Sales'[Region]")


def test_slicers_on_the_page_filter_other_visuals() -> None:
    selection = InCondition(fields=(YEAR,), rows=((num("2025"),),))
    slicer = Visual(
        name="s",
        visual_type="slicer",
        position=POS,
        slicer=SlicerState(field=YEAR, expression=selection),
    )

    result = query_for(visual(TOTAL), slicer)
    assert isinstance(result, DaxQuery)
    assert "TREATAS({2025}, 'Date'[Year])" in result.dax
    assert query_for(slicer) == UnsupportedQuery(
        reason="slicers only filter other visuals"
    )


def test_condition_kinds_become_filter_tables() -> None:
    gt = ComparisonCondition(
        field=REGION,
        operator=">=",
        value=LiteralValue(kind=LiteralKind.TEXT, value="M"),
    )
    either = BinaryCondition(
        kind="or",
        left=gt,
        right=NotCondition(
            operand=InCondition(
                fields=(REGION,),
                rows=((LiteralValue(kind=LiteralKind.NULL, value=""),),),
            )
        ),
    )
    two = InCondition(
        fields=(REGION, YEAR),
        rows=((LiteralValue(kind=LiteralKind.TEXT, value="North"), num("2025")),),
    )
    both = AllCondition(items=(gt, two))

    text_out = dax(visual(TOTAL, filters=(flt(either), flt(both))))

    region = "'Sales'[Region]"
    expected = (
        f'FILTER(ALL({region}), ({region} >= "M") || (NOT({region} IN {{BLANK()}})))'
    )
    assert expected in text_out
    assert "FILTER(ALL('Sales'[Region]), 'Sales'[Region] >= \"M\")" in text_out
    assert "TREATAS({(\"North\", 2025)}, 'Sales'[Region], 'Date'[Year])" in text_out


def test_aggregations_and_duplicate_names() -> None:
    amount = FieldRef(
        table="Sales", name="Amount", kind=FieldKind.AGGREGATION, aggregation="Sum"
    )
    count = FieldRef(
        table="Sales",
        name="Amount",
        kind=FieldKind.AGGREGATION,
        aggregation="DistinctCount",
    )

    result = query_for(visual(REGION, amount, count))

    assert isinstance(result, DaxQuery)
    assert result.values == ("Amount", "Amount (2)")
    assert "\"Amount\", SUM('Sales'[Amount])" in result.dax
    assert "\"Amount (2)\", DISTINCTCOUNT('Sales'[Amount])" in result.dax


@pytest.mark.parametrize(
    ("v", "reason"),
    [
        (
            visual(TOTAL, visual_type="myCustomVisual"),
            "visual type myCustomVisual is not supported",
        ),
        (visual(), "visual has no fields"),
        (
            visual(
                FieldRef(
                    table="Date", name="Calendar.Year", kind=FieldKind.HIERARCHY_LEVEL
                )
            ),
            "hierarchy_level fields are not supported yet",
        ),
        (
            visual(
                FieldRef(
                    table="S",
                    name="A",
                    kind=FieldKind.AGGREGATION,
                    aggregation="Variance",
                )
            ),
            "aggregation Variance is not supported",
        ),
        (
            visual(
                TOTAL,
                filters=(
                    flt(ComparisonCondition(field=TOTAL, operator=">", value=num("1"))),
                ),
            ),
            "filters on measures are not supported yet",
        ),
        (
            visual(
                TOTAL,
                filters=(
                    flt(
                        BinaryCondition(
                            kind="and",
                            left=InCondition(fields=(YEAR,), rows=((num("1"),),)),
                            right=InCondition(fields=(REGION,), rows=((num("2"),),)),
                        )
                    ),
                ),
            ),
            "conditions across several tables are not supported",
        ),
        (
            visual(
                TOTAL,
                filters=(
                    flt(
                        InCondition(
                            fields=(YEAR,),
                            rows=(
                                (LiteralValue(kind=LiteralKind.OTHER, value="infD"),),
                            ),
                        )
                    ),
                ),
            ),
            "literal infD is not supported",
        ),
    ],
)
def test_unsupported_cases_give_reasons(v: Visual, reason: str) -> None:
    assert query_for(v) == UnsupportedQuery(reason=reason)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (LiteralValue(kind=LiteralKind.TEXT, value='say "hi"'), '"say ""hi"""'),
        (LiteralValue(kind=LiteralKind.BOOLEAN, value="true"), "TRUE"),
        (LiteralValue(kind=LiteralKind.NULL, value=""), "BLANK()"),
        (
            LiteralValue(kind=LiteralKind.DATETIME, value="2025-01-31T00:00:00"),
            "DATE(2025, 1, 31)",
        ),
        (
            LiteralValue(kind=LiteralKind.DATETIME, value="2025-01-31T13:05:09"),
            "DATE(2025, 1, 31) + TIME(13, 5, 9)",
        ),
        (num("-3.5"), "-3.5"),
    ],
)
def test_literals(value: LiteralValue, expected: str) -> None:
    assert literal(value) == expected


def test_names_are_quoted_safely() -> None:
    odd = FieldRef(table="Bob's Orders", name="Net [EUR]", kind=FieldKind.COLUMN)

    assert column(odd) == "'Bob''s Orders'[Net [EUR]]]"
    assert text('a"b') == '"a""b"'
