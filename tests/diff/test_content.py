import json

from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.diff.structural import diff_pages_and_visuals
from pbi_report_validator.domain.conditions import render
from pbi_report_validator.domain.models import (
    AllCondition,
    Category,
    ChangeKind,
    ComparisonCondition,
    DiffResult,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    FindingScope,
    LiteralKind,
    LiteralValue,
    Measure,
    MeasureRename,
    Projection,
    Report,
    SemanticModel,
    SlicerState,
    Table,
    Visual,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.matching.matcher import match_reports
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from tests import factories
from tests.factories import FIXTURES, fixture_report

RENAMES = factories.renames(("Sales", "Margin %", "Sales", "Gross Margin %"))


def field(
    name: str, kind: FieldKind = FieldKind.MEASURE, agg: str | None = None
) -> FieldRef:
    return FieldRef(table="Sales", name=name, kind=kind, aggregation=agg)


def visual(
    *projections: Projection,
    filters: tuple[Filter, ...] = (),
    slicer: SlicerState | None = None,
) -> Visual:
    return factories.visual(
        "v", "table", projections=projections, filters=filters, slicer=slicer
    )


def report(v: Visual, filters: tuple[Filter, ...] = ()) -> Report:
    return factories.report(factories.page("p", v), filters=filters)


def content(
    old: Report, new: Report, renames: dict[str, MeasureRename] | None = None
) -> list[tuple[str, Category, ChangeKind, str | None, str | None]]:
    match = match_reports(old.pages, new.pages)
    findings = diff_content(old, new, match, renames or {})
    return sorted((f.path, f.category, f.change, f.old, f.new) for f in findings)


def flt(
    name: str, condition: str | None, level: FilterLevel = FilterLevel.VISUAL
) -> Filter:
    return factories.filter_card(name=name, condition=condition, level=level)


def test_fixture_pair_gives_exactly_the_expected_changes() -> None:
    old_project = load_project(FIXTURES / "sales_v1")
    new_project = load_project(FIXTURES / "sales_v2")
    assert old_project.semantic_model and new_project.semantic_model
    old, new = parse_report(old_project.report), parse_report(new_project.report)
    measures = diff_measures(
        parse_semantic_model(old_project.semantic_model),
        parse_semantic_model(new_project.semantic_model),
    )
    match = match_reports(old.pages, new.pages)

    findings = [
        *diff_pages_and_visuals(match),
        *measures.findings,
        *diff_content(old, new, match, measures.renames),
    ]

    assert sorted((f.path, f.category, f.change) for f in findings) == [
        ("details/chart_sales_by_region", Category.VISUAL, ChangeKind.MOVED),
        (
            "details/table_product_sales/filters/visual_filter_category",
            Category.FILTER,
            ChangeKind.REMOVED,
        ),
        ("model/Sales/Margin %", Category.MEASURE, ChangeKind.RENAMED),
        ("model/Sales/Total Sales", Category.MEASURE, ChangeKind.MODIFIED),
        ("overview/chart_sales_by_month", Category.VISUAL, ChangeKind.RETYPED),
        ("overview/slicer_year", Category.SLICER, ChangeKind.MODIFIED),
        ("trends", Category.PAGE, ChangeKind.ADDED),
    ]
    slicer = next(f for f in findings if f.category == Category.SLICER)
    assert (slicer.old, slicer.new) == ("Date[Year] in (2025)", "Date[Year] in (2024)")


def test_identical_fixture_has_no_content_findings() -> None:
    old = fixture_report("sales_v1")

    assert diff_content(old, old, match_reports(old.pages, old.pages), {}) == []


def test_fields_added_removed_and_moved_between_roles() -> None:
    old = report(
        visual(
            Projection(role="Values", field=field("A")),
            Projection(role="Values", field=field("B")),
        )
    )
    new = report(
        visual(
            Projection(role="Rows", field=field("A")),
            Projection(role="Values", field=field("C")),
        )
    )

    assert content(old, new) == [
        ("p/v/fields/Sales[A]", Category.FIELD, ChangeKind.MODIFIED, "Values", "Rows"),
        ("p/v/fields/Sales[B]", Category.FIELD, ChangeKind.REMOVED, "Values", None),
        ("p/v/fields/Sales[C]", Category.FIELD, ChangeKind.ADDED, None, "Values"),
    ]


def test_aggregation_change_is_a_field_change() -> None:
    old = report(
        visual(
            Projection(role="Y", field=field("Amount", FieldKind.AGGREGATION, "Sum"))
        )
    )
    new = report(
        visual(
            Projection(role="Y", field=field("Amount", FieldKind.AGGREGATION, "Avg"))
        )
    )

    assert [(p, c) for p, _, c, _, _ in content(old, new)] == [
        ("p/v/fields/Sales[Amount] (Avg)", ChangeKind.ADDED),
        ("p/v/fields/Sales[Amount] (Sum)", ChangeKind.REMOVED),
    ]


def test_filter_on_another_aggregation_is_a_filter_change() -> None:
    def card(agg: str) -> Filter:
        amount = field("Amount", FieldKind.AGGREGATION, agg)
        return Filter(
            name="f", level=FilterLevel.VISUAL, filter_type="Advanced", field=amount
        )

    findings = content(
        report(visual(filters=(card("Sum"),))), report(visual(filters=(card("Avg"),)))
    )

    assert [(p, c) for p, c, _, _, _ in findings] == [
        ("p/v/filters/f", Category.FILTER)
    ]


def gt(
    name: str,
    measure: str,
    value: str = "0",
    table: str = "Sales",
    level: FilterLevel = FilterLevel.VISUAL,
) -> Filter:
    """A parsed filter ``Table[measure] > value``, as the parser builds it."""
    expression = ComparisonCondition(
        field=FieldRef(table=table, name=measure, kind=FieldKind.MEASURE),
        operator=">",
        value=LiteralValue(kind=LiteralKind.NUMBER, value=value),
    )
    return factories.filter_card(
        expression, name=name, condition=render(expression), level=level
    )


def test_renamed_measure_references_are_not_reported() -> None:
    old = report(
        visual(
            Projection(role="Values", field=field("Margin %")),
            filters=(gt("f", "Margin %"),),
        ),
        filters=(gt("r", "Margin %", "1", level=FilterLevel.REPORT),),
    )
    new = report(
        visual(
            Projection(role="Values", field=field("Gross Margin %")),
            filters=(gt("f", "Gross Margin %"),),
        ),
        filters=(gt("r", "Gross Margin %", "1", level=FilterLevel.REPORT),),
    )

    assert content(old, new, RENAMES) == []


def test_new_visual_still_using_the_old_name_is_reported() -> None:
    old = report(visual(Projection(role="Values", field=field("Margin %"))))
    new = report(visual(Projection(role="Values", field=field("Margin %"))))

    assert content(old, new, RENAMES) == [
        (
            "p/v/fields/Sales[Gross Margin %]",
            Category.FIELD,
            ChangeKind.REMOVED,
            "Values",
            None,
        ),
        (
            "p/v/fields/Sales[Margin %]",
            Category.FIELD,
            ChangeKind.ADDED,
            None,
            "Values",
        ),
    ]


def test_rename_leaves_longer_table_names_alone() -> None:
    renames = factories.renames(("Data", "Margin", "Data", "Gross Margin"))
    old = report(visual(filters=(gt("f", "Margin", table="Sales Data"),)))
    new = report(visual(filters=(gt("f", "Margin", table="Sales Data"),)))

    assert content(old, new, renames) == []


def test_filters_added_removed_and_changed_at_each_level() -> None:
    old = report(
        visual(filters=(flt("v1", "A"), flt("v2", "B"))),
        filters=(flt("r", "X", FilterLevel.REPORT),),
    )
    new = report(visual(filters=(flt("v1", "A2"), flt("v3", "C"))))

    assert content(old, new) == [
        ("p/v/filters/v1", Category.FILTER, ChangeKind.MODIFIED, "A", "A2"),
        ("p/v/filters/v2", Category.FILTER, ChangeKind.REMOVED, "B", None),
        ("p/v/filters/v3", Category.FILTER, ChangeKind.ADDED, None, "C"),
        ("report/filters/r", Category.FILTER, ChangeKind.REMOVED, "X", None),
    ]


def test_unnamed_filters_are_all_compared() -> None:
    old = report(visual(filters=(flt("", "A"), flt("", "B"))))
    new = report(visual(filters=(flt("", "A"), flt("", "B2"))))

    assert content(old, new) == [
        ("p/v/filters/#2", Category.FILTER, ChangeKind.MODIFIED, "B", "B2"),
    ]


def test_repeated_filter_names_are_all_compared() -> None:
    old = report(visual(filters=(flt("f", "A"), flt("f", "B"), flt("g", "C"))))
    new = report(visual(filters=(flt("f", "A2"), flt("g", "C"))))

    assert content(old, new) == [
        ("p/v/filters/f", Category.FILTER, ChangeKind.MODIFIED, "A", "A2"),
        ("p/v/filters/f#2", Category.FILTER, ChangeKind.REMOVED, "B", None),
    ]


def test_only_report_filters_have_report_scope() -> None:
    old = factories.report(
        factories.page("report", visual(), filters=(flt("p", "A", FilterLevel.PAGE),)),
        filters=(flt("r", "X", FilterLevel.REPORT),),
    )
    new = factories.report(
        factories.page("report", visual(), filters=(flt("p", "B", FilterLevel.PAGE),)),
        filters=(flt("r", "Y", FilterLevel.REPORT),),
    )

    findings = diff_content(old, new, match_reports(old.pages, new.pages), {})

    assert sorted((f.path, f.new, f.scope) for f in findings) == [
        ("report/filters/p", "B", FindingScope.PAGE),
        ("report/filters/r", "Y", FindingScope.REPORT),
    ]


def test_same_named_report_and_page_filter_differ_by_scope_in_the_json() -> None:
    old = factories.report(
        factories.page("report", visual(), filters=(flt("f", "A", FilterLevel.PAGE),)),
        filters=(flt("f", "X", FilterLevel.REPORT),),
    )
    new = factories.report(
        factories.page("report", visual(), filters=(flt("f", "B", FilterLevel.PAGE),)),
        filters=(flt("f", "Y", FilterLevel.REPORT),),
    )
    findings = diff_content(old, new, match_reports(old.pages, new.pages), {})
    result = DiffResult(old_source="old", new_source="new", findings=tuple(findings))

    dumped = json.loads(result.model_dump_json())["findings"]

    assert sorted((f["path"], f["scope"], f["new"]) for f in dumped) == [
        ("report/filters/f", "page", "B"),
        ("report/filters/f", "report", "Y"),
    ]
    assert DiffResult.model_validate_json(result.model_dump_json()) == result


def test_slicer_cleared_is_reported() -> None:
    old = report(visual(slicer=SlicerState(condition="Date[Year] in (2025)")))
    new = report(visual(slicer=SlicerState(condition=None)))

    assert content(old, new) == [
        ("p/v", Category.SLICER, ChangeKind.MODIFIED, "Date[Year] in (2025)", None)
    ]


def test_slicer_selection_added_and_removed_with_visual_type() -> None:
    old_slicer = visual(slicer=SlicerState(condition="Date[Year] in (2025)"))
    no_slicer = visual()

    assert content(report(old_slicer), report(no_slicer)) == [
        ("p/v", Category.SLICER, ChangeKind.REMOVED, "Date[Year] in (2025)", None)
    ]
    assert content(report(no_slicer), report(old_slicer)) == [
        ("p/v", Category.SLICER, ChangeKind.ADDED, None, "Date[Year] in (2025)")
    ]


def test_slicer_without_selection_appearing_is_not_reported() -> None:
    assert content(report(visual()), report(visual(slicer=SlicerState()))) == []


def test_rename_does_not_touch_other_tables_with_similar_names() -> None:
    old = report(visual(filters=(flt("f", "OtherSales[Margin %] > 0"),)))
    new = report(visual(filters=(flt("f", "OtherSales[Margin %] > 0"),)))

    assert content(old, new, RENAMES) == []


def test_chained_renames_are_applied_once() -> None:
    renames = factories.renames(
        ("Sales", "A", "Sales", "B"), ("Sales", "B", "Sales", "C")
    )

    def both(first: str, second: str) -> Filter:
        a, b = gt("f", first).expression, gt("f", second, "1").expression
        assert a is not None and b is not None
        expression = AllCondition(items=(a, b))
        return factories.filter_card(expression, name="f", condition=render(expression))

    old = report(visual(filters=(both("A", "B"),)))
    new = report(visual(filters=(both("B", "C"),)))

    assert content(old, new, renames) == []


def test_same_field_in_two_roles() -> None:
    old = report(visual(Projection(role="Values", field=field("A"))))
    new = report(
        visual(
            Projection(role="Values", field=field("A")),
            Projection(role="Tooltips", field=field("A")),
        )
    )

    assert content(old, new) == [
        (
            "p/v/fields/Sales[A]",
            Category.FIELD,
            ChangeKind.MODIFIED,
            "Values",
            "Tooltips, Values",
        )
    ]


def test_same_filter_values_in_another_order_are_not_reported() -> None:
    old_raw = load_project(FIXTURES / "sales_v1").report
    new_raw = load_project(FIXTURES / "sales_v1").report
    year_filter = new_raw.report.content["filterConfig"]["filters"][0]
    year_filter["filter"]["Where"][0]["Condition"]["In"]["Values"].reverse()
    old, new = parse_report(old_raw), parse_report(new_raw)

    assert diff_content(old, new, match_reports(old.pages, new.pages), {}) == []


def test_measure_moved_to_another_table_is_not_reported_in_the_report() -> None:
    moves = factories.renames(("Sales", "Margin", "Measures", "Margin"))

    def on(table: str) -> Report:
        margin = FieldRef(table=table, name="Margin", kind=FieldKind.MEASURE)
        projection = Projection(role="Values", field=margin)
        return report(visual(projection, filters=(gt("f", "Margin", table=table),)))

    assert content(on("Sales"), on("Measures"), moves) == []
    assert content(on("Sales"), on("Measures")) != []


def sales_eur(measure: str) -> SemanticModel:
    one = Measure(name=measure, expression="1")
    return SemanticModel(tables=(Table(name="Sales [EUR]", measures=(one,)),))


def test_rename_in_a_table_with_brackets_keeps_table_and_name() -> None:
    old_model = sales_eur("Margin")
    new_model = sales_eur("Gross Margin")
    renames = diff_measures(old_model, new_model).renames
    old = report(visual(filters=(gt("f", "Margin", table="Sales [EUR]"),)))
    new = report(visual(filters=(gt("f", "Gross Margin", table="Sales [EUR]"),)))

    assert content(old, new, renames) == []


def test_move_of_a_measure_with_brackets_keeps_table_and_name() -> None:
    moves = factories.renames(("Sales", "Margin [%]", "Measures [x]", "Margin [%]"))
    old = report(visual(filters=(gt("f", "Margin [%]"),)))
    new = report(visual(filters=(gt("f", "Margin [%]", table="Measures [x]"),)))

    assert content(old, new, moves) == []
