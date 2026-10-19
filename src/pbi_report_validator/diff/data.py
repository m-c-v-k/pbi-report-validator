"""Compare what a visual returns in the old and new version.

Rows are aligned on the group-by columns, then each value is compared:
text exactly, numbers within a ``Tolerance``.

Alignment: each result becomes a frame whose columns are renamed to
``key0, key1, ...`` and ``value0, value1, ...`` (so old and new line up even
when a measure was renamed). The two frames are outer-joined on the key
columns; pandas then suffixes the value columns with ``_old``/``_new`` and
records in ``SIDE`` whether a row was in both versions or only one. A visual
without group-by columns has one row, joined on a constant ``NO_KEY`` column.
Findings are capped per visual; the ``DataSummary`` keeps the full counts.
Row keys and values are masked unless asked for, since they are row-level
data that can end up in public job summaries and pull request comments.
Pure functions only: the query results come in as domain models.
"""

from collections.abc import Iterable, Sequence

import pandas as pd

from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.models import (
    Category,
    CellValue,
    ChangeKind,
    DataComparison,
    DataStatus,
    DataSummary,
    Finding,
    QueryResult,
    RowComparison,
    Tolerance,
)

DEFAULT_MAX_FINDINGS = 20
TOTAL_LABEL = "total"
MASKED = "(masked)"
# Columns added by the outer join; the SIDE values are pandas' own names.
SIDE = "_merge"
BOTH = "both"
OLD_ONLY = "left_only"
NEW_ONLY = "right_only"
NO_KEY = "_row"
OLD_SUFFIX = "_old"
NEW_SUFFIX = "_new"

ColumnPairs = Sequence[tuple[str, str]]


class ComparisonError(ValueError):
    """The two results cannot be compared row by row."""


def compare_results(
    path: str,
    old: QueryResult,
    new: QueryResult,
    keys: ColumnPairs,
    values: ColumnPairs,
    tolerance: Tolerance | None = None,
    max_findings: int = DEFAULT_MAX_FINDINGS,
    *,
    show_values: bool = False,
) -> DataComparison:
    """Compare two query results for the visual at ``path`` (``page/visual``).

    Args:
        path: The visual's path, used as prefix for finding paths.
        old: Result of the old version's query.
        new: Result of the new version's query.
        keys: ``(old column, new column)`` pairs to align rows on; empty for
            visuals without group-by (cards).
        values: ``(old column, new column)`` pairs to compare.
        tolerance: Allowed difference for numbers.
        max_findings: Maximum findings returned for this visual.
        show_values: Put row keys and values in the findings. When false,
            rows are named ``row N`` (their position in the sorted rows) and
            values are ``(masked)``.

    Returns:
        The summary and the (capped) findings. Results that cannot be aligned
        give a ``not_validated`` summary with the reason.
    """
    tolerance = tolerance or Tolerance()
    try:
        old_frame = _frame(old, keys, values, side=0, label="old")
        new_frame = _frame(new, keys, values, side=1, label="new")
    except ComparisonError as exc:
        return not_validated(path, str(exc))
    merged = _merge(old_frame, new_frame, len(keys))
    rows = _compare_rows(path, merged, keys, values, tolerance, show_values)
    summary = DataSummary(
        path=path,
        status=DataStatus.DIFFERENT if rows.findings else DataStatus.SAME,
        rows_old=len(old_frame),
        rows_new=len(new_frame),
        rows_matched=_count(merged, BOTH),
        rows_differing=rows.rows_differing,
        rows_only_old=_count(merged, OLD_ONLY),
        rows_only_new=_count(merged, NEW_ONLY),
        max_abs_delta=max(rows.deltas) if rows.deltas else None,
    )
    return DataComparison(summary=summary, findings=rows.findings[:max_findings])


def _compare_rows(
    path: str,
    merged: pd.DataFrame,
    keys: ColumnPairs,
    values: ColumnPairs,
    tolerance: Tolerance,
    show_values: bool,
) -> RowComparison:
    """Findings, number of differing matched rows and all numeric deltas."""
    names = [old_name for old_name, _ in keys]
    findings: list[Finding] = []
    differing = 0
    deltas: list[float] = []
    for position, (_, row) in enumerate(merged.iterrows(), start=1):
        key_values = [row[_key_column(i)] for i in range(len(keys))]
        label = (
            _label(names, key_values) if show_values else _masked_label(names, position)
        )
        if row[SIDE] != BOTH:
            subject = f"Row {label}" if show_values else label.capitalize()
            only_new = row[SIDE] == NEW_ONLY
            findings.append(_row_finding(path, label, subject, only_new))
            continue
        row_findings, row_deltas = _compare_row(
            path, label, row, values, tolerance, show_values
        )
        findings += row_findings
        deltas += row_deltas
        differing += bool(row_findings)
    return RowComparison(
        findings=tuple(findings), rows_differing=differing, deltas=tuple(deltas)
    )


def _compare_row(
    path: str,
    label: str,
    row: pd.Series,
    values: ColumnPairs,
    tolerance: Tolerance,
    show_values: bool,
) -> tuple[list[Finding], list[float]]:
    """Value findings and numeric deltas for one row present in both versions."""
    findings: list[Finding] = []
    deltas: list[float] = []
    for index, (value_name, _) in enumerate(values):
        column = _value_column(index)
        before = _cell(row[column + OLD_SUFFIX])
        after = _cell(row[column + NEW_SUFFIX])
        equal, delta = _equal(before, after, tolerance)
        if delta is not None:
            deltas.append(delta)
        if not equal:
            shown = (
                (display(before), display(after)) if show_values else (MASKED, MASKED)
            )
            findings.append(_value_finding(path, label, value_name, *shown))
    return findings, deltas


def _count(merged: pd.DataFrame, side: str) -> int:
    return int((merged[SIDE] == side).sum())


def not_validated(path: str, reason: str) -> DataComparison:
    """A visual whose data could not be compared, with the reason."""
    finding = make_finding(
        Category.DATA,
        ChangeKind.ERROR,
        path=f"{path}/data",
        message=f"Data not validated: {reason}",
    )
    summary = DataSummary(path=path, status=DataStatus.NOT_VALIDATED, reason=reason)
    return DataComparison(summary=summary, findings=(finding,))


def not_fully_validated(findings: Iterable[Finding]) -> list[Finding]:
    """The findings of visuals whose data was not, or only partly, compared."""
    return [
        f
        for f in findings
        if (f.category, f.change) == (Category.DATA, ChangeKind.ERROR)
    ]


def _frame(
    result: QueryResult, keys: ColumnPairs, values: ColumnPairs, side: int, label: str
) -> pd.DataFrame:
    """Result as a frame with canonical columns ``key0.., value0..``."""
    wanted = [pair[side] for pair in [*keys, *values]]
    canonical = [_key_column(i) for i in range(len(keys))] + [
        _value_column(i) for i in range(len(values))
    ]
    # The API returns no column names for a result without rows, so columns
    # can only be checked when there are some.
    missing = [name for name in wanted if name not in result.columns]
    if result.columns and missing:
        raise ComparisonError(f"{label} result has no column {', '.join(missing)}")
    if not result.rows:
        return pd.DataFrame(columns=canonical, dtype=object)
    frame = pd.DataFrame(list(result.rows), columns=list(result.columns), dtype=object)
    frame = frame[wanted].set_axis(canonical, axis=1)
    if keys and frame.duplicated(subset=canonical[: len(keys)]).any():
        raise ComparisonError(f"{label} result has several rows for the same key")
    if not keys and len(frame) > 1:
        raise ComparisonError(f"{label} result has several rows but no key columns")
    return frame


def _key_column(index: int) -> str:
    return f"key{index}"


def _value_column(index: int) -> str:
    return f"value{index}"


def _merge(old: pd.DataFrame, new: pd.DataFrame, key_count: int) -> pd.DataFrame:
    """Outer-join the two frames on their keys, sorted by key.

    The result has the ``SIDE`` column and each value column twice, with
    ``OLD_SUFFIX`` and ``NEW_SUFFIX``.
    """
    on = [_key_column(i) for i in range(key_count)] or [NO_KEY]
    if not key_count:
        old, new = old.assign(**{NO_KEY: 0}), new.assign(**{NO_KEY: 0})
    merged = old.merge(
        new, on=on, how="outer", suffixes=(OLD_SUFFIX, NEW_SUFFIX), indicator=SIDE
    )
    merged[SIDE] = merged[SIDE].astype(str)
    order = merged[on].map(_sort_key).apply(tuple, axis=1)
    return merged.loc[order.sort_values(kind="stable").index]


def _equal(
    before: CellValue, after: CellValue, tolerance: Tolerance
) -> tuple[bool, float | None]:
    """Whether two values are equal, and their numeric difference if any."""
    a, b = _number(before), _number(after)
    if a is not None and b is not None:
        delta = abs(a - b)
        allowed = max(tolerance.absolute, tolerance.relative * max(abs(a), abs(b)))
        return delta <= allowed, delta
    return before == after, None


def _number(value: CellValue) -> float | None:
    """The value as a float if it is a number (booleans are not)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _cell(value: object) -> CellValue:
    """A merged cell back as a plain value (pandas uses NaN for gaps)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _row_finding(path: str, label: str, subject: str, only_new: bool) -> Finding:
    where = "new" if only_new else "old"
    change = ChangeKind.ADDED if only_new else ChangeKind.REMOVED
    return make_finding(
        Category.DATA,
        change,
        path=f"{path}/data/{label}",
        message=f"{subject} only in the {where} version",
    )


def _value_finding(
    path: str, label: str, name: str, before: str, after: str
) -> Finding:
    return make_finding(
        Category.DATA,
        ChangeKind.MODIFIED,
        path=f"{path}/data/{label}/{name}",
        message=f"{name} differs for {label}",
        old=before,
        new=after,
    )


def _label(names: Sequence[str], values: Sequence[object]) -> str:
    if not names:
        return TOTAL_LABEL
    return ", ".join(
        f"{n}={display(_cell(v))}" for n, v in zip(names, values, strict=True)
    )


def _masked_label(names: Sequence[str], position: int) -> str:
    """A row named by its position, so findings do not reveal key values."""
    return f"row {position}" if names else TOTAL_LABEL


def display(value: CellValue) -> str:
    """A value as shown in findings: blanks marked, whole floats as integers."""
    if value is None:
        return "(blank)"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _sort_key(value: object) -> tuple[int, float, str]:
    """Blanks first, then numbers in numeric order, then everything else."""
    cell = _cell(value)
    if cell is None:
        return (0, 0.0, "")
    number = _number(cell)
    if number is not None:
        return (1, number, "")
    return (2, 0.0, f"{type(cell).__name__}:{cell}")
