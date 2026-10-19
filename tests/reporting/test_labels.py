from pbi_report_validator.domain.models import (
    Category,
    DataStatus,
    DataSummary,
    DiffResult,
    ItemStatus,
)
from pbi_report_validator.reporting.labels import (
    CATEGORY_LABELS,
    STATUS_LABELS,
    STATUS_MARKS,
    data_overview,
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
