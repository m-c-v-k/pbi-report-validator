import pytest

from pbi_report_validator.diff.data import compare_results, display, not_validated
from pbi_report_validator.domain.models import (
    Category,
    CellValue,
    ChangeKind,
    DataStatus,
    QueryResult,
    Tolerance,
)

PATH = "overview/chart"
KEYS = [("Date[Month]", "Date[Month]")]
VALUES = [("[Total Sales]", "[Total Sales]")]


def result(
    *rows: tuple[CellValue, ...],
    columns: tuple[str, ...] = ("Date[Month]", "[Total Sales]"),
) -> QueryResult:
    return QueryResult(columns=columns, rows=rows)


def test_identical_results_are_same() -> None:
    data = result(("2025-01", 100.0), ("2025-02", 50))

    comparison = compare_results(PATH, data, data, KEYS, VALUES)

    assert comparison.findings == ()
    s = comparison.summary
    assert (s.status, s.rows_old, s.rows_new, s.rows_matched, s.rows_differing) == (
        DataStatus.SAME,
        2,
        2,
        2,
        0,
    )
    assert s.max_abs_delta == 0.0


def test_value_change_outside_tolerance_is_reported() -> None:
    old = result(("2025-01", 100.0), ("2025-02", 50.0))
    new = result(("2025-02", 50.0), ("2025-01", 120.0))

    comparison = compare_results(PATH, old, new, KEYS, VALUES)

    assert [
        (f.category, f.change, f.path, f.old, f.new) for f in comparison.findings
    ] == [
        (
            Category.DATA,
            ChangeKind.MODIFIED,
            "overview/chart/data/Date[Month]=2025-01/[Total Sales]",
            "100",
            "120",
        ),
    ]
    assert comparison.summary.status == DataStatus.DIFFERENT
    assert comparison.summary.rows_differing == 1
    assert comparison.summary.max_abs_delta == 20.0


@pytest.mark.parametrize(
    ("tolerance", "equal"),
    [
        (Tolerance(), False),
        (Tolerance(absolute=0.5), True),
        (Tolerance(relative=0.01), True),
        (Tolerance(relative=0.001), False),
    ],
)
def test_tolerances(tolerance: Tolerance, equal: bool) -> None:
    comparison = compare_results(
        PATH, result(("a", 100.0)), result(("a", 100.4)), KEYS, VALUES, tolerance
    )

    assert (comparison.summary.status == DataStatus.SAME) is equal


def test_rows_only_in_one_version() -> None:
    old = result(("2025-01", 1), ("2025-03", 3))
    new = result(("2025-01", 1), ("2025-02", 2))

    comparison = compare_results(PATH, old, new, KEYS, VALUES)

    assert [(f.change, f.path) for f in comparison.findings] == [
        (ChangeKind.ADDED, "overview/chart/data/Date[Month]=2025-02"),
        (ChangeKind.REMOVED, "overview/chart/data/Date[Month]=2025-03"),
    ]
    s = comparison.summary
    assert (s.rows_only_old, s.rows_only_new, s.rows_matched) == (1, 1, 1)


def test_blanks_and_text_values() -> None:
    columns = ("Product[Category]", "[Label]", "[Value]")
    old = result(("Bikes", "high", None), ("Clothing", "low", 5), columns=columns)
    new = result(("Bikes", "high", None), ("Clothing", "LOW", None), columns=columns)
    keys = [("Product[Category]", "Product[Category]")]
    values = [("[Label]", "[Label]"), ("[Value]", "[Value]")]

    comparison = compare_results(PATH, old, new, keys, values)

    assert [(f.path.rsplit("/", 1)[-1], f.old, f.new) for f in comparison.findings] == [
        ("[Label]", "low", "LOW"),
        ("[Value]", "5", "(blank)"),
    ]
    assert comparison.summary.rows_differing == 1


def test_card_without_keys_compares_the_single_row() -> None:
    columns = ("[Total]",)

    comparison = compare_results(
        PATH,
        result((10,), columns=columns),
        result((12,), columns=columns),
        [],
        [("[Total]", "[Total]")],
    )

    assert [(f.path, f.old, f.new) for f in comparison.findings] == [
        ("overview/chart/data/total/[Total]", "10", "12"),
    ]


def test_renamed_value_columns_are_paired_explicitly() -> None:
    old = result(("a", 1), columns=("Date[Month]", "[Margin %]"))
    new = result(("a", 1), columns=("Date[Month]", "[Gross Margin %]"))

    comparison = compare_results(
        PATH, old, new, KEYS, [("[Margin %]", "[Gross Margin %]")]
    )

    assert comparison.summary.status == DataStatus.SAME


def test_empty_results() -> None:
    assert (
        compare_results(PATH, QueryResult(), QueryResult(), KEYS, VALUES).summary.status
        == DataStatus.SAME
    )
    one_side = compare_results(PATH, QueryResult(), result(("a", 1)), KEYS, VALUES)
    assert [f.change for f in one_side.findings] == [ChangeKind.ADDED]


@pytest.mark.parametrize(
    ("old", "reason"),
    [
        (
            result(("a", 1), columns=("Date[Month]", "[Other]")),
            "old result has no column [Total Sales]",
        ),
        (result(("a", 1), ("a", 2)), "old result has several rows for the same key"),
    ],
)
def test_results_that_cannot_be_aligned_are_not_validated(
    old: QueryResult, reason: str
) -> None:
    comparison = compare_results(PATH, old, result(("a", 1)), KEYS, VALUES)

    assert comparison.summary.status == DataStatus.NOT_VALIDATED
    assert comparison.summary.reason == reason
    assert comparison.findings[0].change == ChangeKind.ERROR


def test_findings_are_capped_but_summary_counts_everything() -> None:
    old = result(*[(f"m{i:02}", i) for i in range(30)])
    new = result(*[(f"m{i:02}", i + 1) for i in range(30)])

    comparison = compare_results(PATH, old, new, KEYS, VALUES, max_findings=5)

    assert len(comparison.findings) == 5
    assert comparison.findings[0].path.endswith("Date[Month]=m00/[Total Sales]")
    assert comparison.summary.rows_differing == 30


def test_mixed_key_types_sort_deterministically() -> None:
    columns = ("T[K]", "[V]")
    old = result((2, 1), ("b", 1), (None, 1), columns=columns)
    new = result(("b", 2), (2, 2), (None, 2), columns=columns)

    first = compare_results(PATH, old, new, [("T[K]", "T[K]")], [("[V]", "[V]")])
    second = compare_results(PATH, old, new, [("T[K]", "T[K]")], [("[V]", "[V]")])

    assert first == second
    assert len(first.findings) == 3


def test_not_validated_helper() -> None:
    comparison = not_validated(PATH, "visual type map is not supported")

    assert comparison.findings[0].path == "overview/chart/data"
    assert (
        comparison.findings[0].message
        == "Data not validated: visual type map is not supported"
    )


@pytest.mark.parametrize(
    ("value", "text"),
    [(None, "(blank)"), (3.0, "3"), (2.5, "2.5"), (True, "True"), ("x", "x")],
)
def test_display(value: CellValue, text: str) -> None:
    assert display(value) == text


def test_empty_result_with_wrong_columns_is_not_validated() -> None:
    wrong = QueryResult(columns=("Date[Month]", "[Other]"), rows=())

    comparison = compare_results(PATH, wrong, result(("a", 1)), KEYS, VALUES)

    assert comparison.summary.status == DataStatus.NOT_VALIDATED


def test_numeric_keys_sort_naturally() -> None:
    columns = ("Date[Year]", "[V]")
    old = result((9, 1), (10, 1), (2024, 1), columns=columns)
    new = result((9, 2), (10, 2), (2024, 2), columns=columns)

    comparison = compare_results(
        PATH, old, new, [("Date[Year]", "Date[Year]")], [("[V]", "[V]")]
    )

    assert [f.path.split("=")[1].split("/")[0] for f in comparison.findings] == [
        "9",
        "10",
        "2024",
    ]
