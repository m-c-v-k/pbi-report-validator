from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.diff.structural import diff_pages_and_visuals
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    Projection,
    Report,
    SlicerState,
    Visual,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.matching.matcher import match_reports
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from tests import factories
from tests.factories import FIXTURES, fixture_report

RENAMES = {"Sales[Margin %]": "Sales[Gross Margin %]"}


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
    old: Report, new: Report, renames: dict[str, str] | None = None
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


def test_renamed_measure_references_are_not_reported() -> None:
    old = report(
        visual(
            Projection(role="Values", field=field("Margin %")),
            filters=(flt("f", "Sales[Margin %] > 0"),),
        ),
        filters=(flt("r", "Sales[Margin %] > 1", FilterLevel.REPORT),),
    )
    new = report(
        visual(
            Projection(role="Values", field=field("Gross Margin %")),
            filters=(flt("f", "Sales[Gross Margin %] > 0"),),
        ),
        filters=(flt("r", "Sales[Gross Margin %] > 1", FilterLevel.REPORT),),
    )

    assert content(old, new, RENAMES) == []


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
    renames = {"Sales[A]": "Sales[B]", "Sales[B]": "Sales[C]"}
    old = report(visual(filters=(flt("f", "Sales[A] > 0 and Sales[B] > 1"),)))
    new = report(visual(filters=(flt("f", "Sales[B] > 0 and Sales[C] > 1"),)))

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
