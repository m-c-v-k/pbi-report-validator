from typing import get_args

import pytest
from pydantic import ValidationError

from pbi_report_validator.domain.models import (
    SCHEMA_VERSION,
    Category,
    ChangeKind,
    DiffResult,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    Finding,
    Measure,
    Page,
    ParseIssue,
    Position,
    Projection,
    Report,
    SemanticModel,
    Severity,
    SeverityCounts,
    SlicerState,
    Table,
    Visual,
)

TOTAL_SALES = FieldRef(table="Sales", name="Total Sales", kind=FieldKind.MEASURE)
YEAR = FieldRef(table="Date", name="Year", kind=FieldKind.COLUMN)


def make_report() -> Report:
    slicer = Visual(
        name="slicer_year",
        visual_type="slicer",
        position=Position(x=0, y=0, width=200, height=100),
        projections=(Projection(role="Values", field=YEAR),),
        slicer=SlicerState(field=YEAR, condition="Date[Year] in (2025)"),
    )
    card = Visual(
        name="card_total_sales",
        visual_type="card",
        title="Total sales",
        position=Position(x=10, y=20, z=1000, width=280, height=140),
        projections=(Projection(role="Values", field=TOTAL_SALES),),
        filters=(
            Filter(
                name="f1",
                level=FilterLevel.VISUAL,
                field=YEAR,
                filter_type="Categorical",
                condition="Date[Year] in (2024, 2025)",
            ),
        ),
    )
    page = Page(
        name="overview",
        display_name="Overview",
        ordinal=0,
        width=1280,
        height=720,
        visuals=(card, slicer),
    )
    return Report(pages=(page,))


def test_report_round_trips_through_json() -> None:
    report = make_report()

    assert Report.model_validate_json(report.model_dump_json()) == report


def test_semantic_model_round_trips_through_json() -> None:
    model = SemanticModel(
        tables=(
            Table(
                name="Sales",
                measures=(
                    Measure(name="Total Sales", expression="SUM(Sales[Amount])"),
                ),
            ),
        )
    )

    assert SemanticModel.model_validate_json(model.model_dump_json()) == model


def test_field_ref_key_is_dax_style() -> None:
    assert TOTAL_SALES.key == "Sales[Total Sales]"


@pytest.mark.parametrize("field", ["x", "y", "width", "height"])
def test_position_rejects_negative_values(field: str) -> None:
    values = {"x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0, field: -1.0}

    with pytest.raises(ValidationError):
        Position.model_validate(values)


def test_page_rejects_zero_size() -> None:
    with pytest.raises(ValidationError):
        Page(name="p", display_name="P", ordinal=0, width=0, height=720)


def test_models_are_frozen() -> None:
    with pytest.raises(ValidationError):
        TOTAL_SALES.name = "Other"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        FieldRef.model_validate(
            {"table": "Sales", "name": "Amount", "kind": "column", "extra": 1}
        )


def test_diff_result_sorts_findings_and_sets_schema_version() -> None:
    later = Finding(
        category=Category.VISUAL,
        change=ChangeKind.MOVED,
        path="overview/chart",
        message="Visual moved",
    )
    earlier = Finding(
        category=Category.PAGE,
        change=ChangeKind.ADDED,
        path="details",
        message="Page added",
    )

    result = DiffResult(old_source="old", new_source="new", findings=(later, earlier))

    assert result.findings == (earlier, later)
    assert result.schema_version == SCHEMA_VERSION
    assert DiffResult.model_validate_json(result.model_dump_json()) == result


def test_diff_result_order_is_independent_of_input_order() -> None:
    first = Finding(
        category=Category.FILTER,
        change=ChangeKind.MODIFIED,
        path="overview/card",
        message="Filter changed",
        old="a",
        new="b",
    )
    second = first.model_copy(update={"old": "c", "new": "d"})

    forward = DiffResult(old_source="o", new_source="n", findings=(first, second))
    backward = DiffResult(old_source="o", new_source="n", findings=(second, first))

    assert forward.findings == backward.findings == (first, second)


def test_severity_counts_are_derived_from_findings() -> None:
    finding = Finding(
        category=Category.FILTER,
        change=ChangeKind.REMOVED,
        severity=Severity.CRITICAL,
        path="p/v/filters/f",
        message="Filter removed",
    )
    info = finding.model_copy(update={"severity": Severity.INFO, "path": "p"})

    result = DiffResult(
        old_source="o",
        new_source="n",
        findings=(finding, info),
        severity_counts=SeverityCounts(warning=5),
    )

    assert result.severity_counts == SeverityCounts(critical=1, info=1)
    assert DiffResult.model_validate_json(result.model_dump_json()) == result


def test_schema_version_literal_matches_constant() -> None:
    annotation = DiffResult.model_fields["schema_version"].annotation

    assert get_args(annotation) == (SCHEMA_VERSION,)


def test_page_rejects_negative_ordinal() -> None:
    with pytest.raises(ValidationError):
        Page(name="p", display_name="P", ordinal=-1, width=1280, height=720)


def test_report_keeps_parse_issues() -> None:
    issue = ParseIssue(path="pages/p/visuals/v/visual.json", message="invalid JSON")

    report = Report(issues=(issue,))

    assert Report.model_validate_json(report.model_dump_json()).issues == (issue,)
