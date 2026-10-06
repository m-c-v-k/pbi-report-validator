"""Compare what a visual returns in the old and new version.

Rows are aligned on the group-by columns (an outer join in pandas), then
each value is compared: text exactly, numbers within a ``Tolerance``.
Findings are capped per visual; the ``DataSummary`` keeps the full counts.
Pure functions only: the query results come in as domain models.
"""

from collections.abc import Sequence

import pandas as pd

from pbi_report_validator.domain.models import (
    Category,
    CellValue,
    ChangeKind,
    DataComparison,
    DataStatus,
    DataSummary,
    Finding,
    QueryResult,
    Tolerance,
)

DEFAULT_MAX_FINDINGS = 20
TOTAL_LABEL = "total"
SIDE = "_merge"

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
    names = [old_name for old_name, _ in keys]
    findings: list[Finding] = []
    differing = 0
    deltas: list[float] = []
    for _, row in merged.iterrows():
        label = _label(names, [row[f"k{i}"] for i in range(len(keys))])
        side = row[SIDE]
        if side != "both":
            findings.append(_row_finding(path, label, side == "right_only"))
            continue
        changed = False
        for index, (value_name, _) in enumerate(values):
            before, after = _cell(row[f"v{index}_old"]), _cell(row[f"v{index}_new"])
            equal, delta = _equal(before, after, tolerance)
            if delta is not None:
                deltas.append(delta)
            if not equal:
                changed = True
                findings.append(_value_finding(path, label, value_name, before, after))
        differing += changed
    only_old = int((merged[SIDE] == "left_only").sum())
    only_new = int((merged[SIDE] == "right_only").sum())
    summary = DataSummary(
        path=path,
        status=DataStatus.DIFFERENT if findings else DataStatus.SAME,
        rows_old=len(old_frame),
        rows_new=len(new_frame),
        rows_matched=int((merged[SIDE] == "both").sum()),
        rows_differing=differing,
        rows_only_old=only_old,
        rows_only_new=only_new,
        max_abs_delta=max(deltas) if deltas else None,
    )
    return DataComparison(summary=summary, findings=tuple(findings[:max_findings]))


def not_validated(path: str, reason: str) -> DataComparison:
    """A visual whose data could not be compared, with the reason."""
    finding = Finding(
        category=Category.DATA,
        change=ChangeKind.ERROR,
        path=f"{path}/data",
        message=f"Data not validated: {reason}",
    )
    summary = DataSummary(path=path, status=DataStatus.NOT_VALIDATED, reason=reason)
    return DataComparison(summary=summary, findings=(finding,))


def _frame(
    result: QueryResult, keys: ColumnPairs, values: ColumnPairs, side: int, label: str
) -> pd.DataFrame:
    """Result as a frame with canonical column names ``k0.., v0..``."""
    wanted = [pair[side] for pair in [*keys, *values]]
    canonical = [f"k{i}" for i in range(len(keys))] + [
        f"v{i}" for i in range(len(values))
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


def _merge(old: pd.DataFrame, new: pd.DataFrame, key_count: int) -> pd.DataFrame:
    on = [f"k{i}" for i in range(key_count)] or ["_row"]
    if not key_count:
        old, new = old.assign(_row=0), new.assign(_row=0)
    merged = old.merge(
        new, on=on, how="outer", suffixes=("_old", "_new"), indicator=SIDE
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


def _row_finding(path: str, label: str, only_new: bool) -> Finding:
    where = "new" if only_new else "old"
    return Finding(
        category=Category.DATA,
        change=ChangeKind.ADDED if only_new else ChangeKind.REMOVED,
        path=f"{path}/data/{label}",
        message=f"Row {label} only in the {where} version",
    )


def _value_finding(
    path: str, label: str, name: str, before: CellValue, after: CellValue
) -> Finding:
    return Finding(
        category=Category.DATA,
        change=ChangeKind.MODIFIED,
        path=f"{path}/data/{label}/{name}",
        message=f"{name} differs for {label}",
        old=display(before),
        new=display(after),
    )


def _label(names: Sequence[str], values: Sequence[object]) -> str:
    if not names:
        return TOTAL_LABEL
    return ", ".join(
        f"{n}={display(_cell(v))}" for n, v in zip(names, values, strict=True)
    )


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
