from pbi_report_validator.domain.models import (
    AiMode,
    Category,
    ChangeKind,
    DataStatus,
    DataSummary,
    DiffResult,
    Finding,
    ItemStatus,
    Severity,
    SourceLocation,
)
from pbi_report_validator.reporting.labels import (
    CATEGORY_LABELS,
    STATUS_LABELS,
    STATUS_MARKS,
    ai_overview,
    data_overview,
    source_locations,
)


def test_every_category_and_status_has_a_label() -> None:
    assert set(CATEGORY_LABELS) == set(Category)
    assert set(STATUS_LABELS) == set(ItemStatus)
    assert set(STATUS_MARKS) == set(ItemStatus)


def test_data_overview_only_when_data_was_compared() -> None:
    assert data_overview(DiffResult(old_source="o", new_source="n")) is None

    result = DiffResult(
        old_source="o",
        new_source="n",
        data=(
            DataSummary(path="p/a", status=DataStatus.SAME),
            DataSummary(path="p/b", status=DataStatus.NOT_VALIDATED, reason="x"),
        ),
    )

    assert data_overview(result) == (
        "Data: 2 visuals compared, 1 same, 0 different, 1 not validated"
    )


def test_ai_overview_only_when_ai_was_on() -> None:
    assert ai_overview(DiffResult(old_source="o", new_source="n")) is None

    result = DiffResult(
        old_source="o", new_source="n", ai_mode=AiMode.API, ai_model="claude-x"
    )

    assert ai_overview(result) == (
        "AI: api (claude-x). AI output is labelled 'AI-generated'; "
        "the findings themselves are not."
    )


HERE = SourceLocation(file="a/visual.json", pointer="/filterConfig/filters/0")
THERE = SourceLocation(file="b/visual.json", pointer="")


def located(old: SourceLocation | None, new: SourceLocation | None) -> Finding:
    return Finding(
        category=Category.FILTER,
        change=ChangeKind.MODIFIED,
        severity=Severity.CRITICAL,
        path="p/v/filters/f",
        message="Filter f changed",
        old_location=old,
        new_location=new,
    )


def test_source_locations_are_merged_when_both_sides_agree() -> None:
    assert source_locations(located(HERE, HERE)) == [("Defined in", HERE)]
    assert source_locations(located(HERE, THERE)) == [("Old", HERE), ("New", THERE)]
    assert source_locations(located(None, THERE)) == [("New", THERE)]
    assert source_locations(located(HERE, None)) == [("Old", HERE)]
    assert source_locations(located(None, None)) == []
