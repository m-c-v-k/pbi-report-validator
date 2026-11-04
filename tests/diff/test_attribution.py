import pytest

from pbi_report_validator.diff.attribution import NOT_REPRODUCED, attribute_difference
from pbi_report_validator.domain.models import Attribution, QueryResult, Tolerance

KEYS = [("Date[Month]", "Date[Month]")]
VALUES = [("[Margin %]", "[Gross Margin %]")]


def result(value: float, name: str = "[Margin %]") -> QueryResult:
    return QueryResult(
        columns=("Date[Month]", name),
        rows=(("2025-01", 100.0), ("2025-02", value)),
    )


def attribute(
    old: float, cross: float, new: float, tolerance: Tolerance | None = None
) -> tuple[Attribution, str | None]:
    results = (
        result(old),
        result(cross, "[Gross Margin %]"),
        result(new, "[Gross Margin %]"),
    )
    return attribute_difference("p/v", results, KEYS, VALUES, tolerance or Tolerance())


@pytest.mark.parametrize(
    ("old", "cross", "new", "expected"),
    [
        (100.0, 120.0, 120.0, Attribution.REPORT),
        (100.0, 100.0, 120.0, Attribution.MODEL),
        (100.0, 110.0, 120.0, Attribution.BOTH),
    ],
)
def test_attribution_follows_which_step_changes_the_numbers(
    old: float, cross: float, new: float, expected: Attribution
) -> None:
    assert attribute(old, cross, new) == (expected, None)


def test_difference_split_below_the_tolerance_is_unknown() -> None:
    # 100 -> 105 -> 110: each step is within 5, the whole change is not.
    tolerance = Tolerance(absolute=5.0, relative=0.0)

    assert attribute(100.0, 105.0, 110.0, tolerance) == (
        Attribution.UNKNOWN,
        NOT_REPRODUCED,
    )


def test_cross_result_that_cannot_be_aligned_is_unknown() -> None:
    old = result(100.0)
    cross = QueryResult(columns=("Date[Month]",), rows=(("2025-01",),))
    new = result(120.0, "[Gross Margin %]")

    attribution, reason = attribute_difference(
        "p/v", (old, cross, new), KEYS, VALUES, Tolerance()
    )

    assert attribution is Attribution.UNKNOWN
    assert reason is not None
    assert reason.startswith("the report change: ")
