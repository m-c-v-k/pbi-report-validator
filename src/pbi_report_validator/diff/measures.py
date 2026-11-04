"""Diff the measures of two semantic model versions.

A measure that disappears from a table while a measure with the same
expression appears in the same table is reported once as a rename, and
one that disappears from a table while a measure with the same name and
expression appears in another table is reported once as a move. The
resulting rename map lets the report diff ignore field references that
only changed because of that rename or move.

Limitation: a measure that is renamed *and* has its expression edited in
the same change cannot be recognised. It is reported as removed plus
added, and fields and filters that use it are reported as changed too.
"""

from typing import NamedTuple

from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.helpers import field_key, unique_by
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Finding,
    Measure,
    MeasureDiff,
    SemanticModel,
)

MODEL_PATH = "model"
# A measure with the name of the table it is in.
TableMeasure = tuple[str, Measure]


def diff_measures(old: SemanticModel | None, new: SemanticModel | None) -> MeasureDiff:
    """Compare measures table by table.

    Args:
        old: The old semantic model, or ``None`` if it was not available.
        new: The new semantic model, or ``None`` if it was not available.

    Returns:
        Added, removed, renamed and modified measures, and a map from old
        to new DAX key (``Sales[Margin %]`` -> ``Sales[Gross Margin %]``).
        Nothing is compared unless both models are available. A table
        declared in several files is compared as one, and a measure that
        could not be parsed in one version is not reported as added or
        removed (its parse issue already is).
    """
    if old is None or new is None:
        return MeasureDiff()
    old_tables, new_tables = _measures_by_table(old), _measures_by_table(new)
    unparsed = _unparsed_measures(old) | _unparsed_measures(new)
    findings: list[Finding] = []
    renames: dict[str, str] = {}
    removed: list[TableMeasure] = []
    added: list[TableMeasure] = []
    for table in sorted(old_tables.keys() | new_tables.keys()):
        table_diff = _diff_table(
            table, old_tables.get(table, ()), new_tables.get(table, ()), unparsed
        )
        findings += table_diff.findings
        renames.update(table_diff.renames)
        removed += [(table, m) for m in table_diff.removed]
        added += [(table, m) for m in table_diff.added]
    moves = _moved_pairs(removed, added)
    findings += [_moved(old, new) for old, new in moves]
    for (old_table, measure), (new_table, _) in moves:
        renames[field_key(old_table, measure.name)] = field_key(new_table, measure.name)
    moved = {item for pair in moves for item in pair}
    findings += [_removed(t, m) for t, m in removed if (t, m) not in moved]
    findings += [_added(t, m) for t, m in added if (t, m) not in moved]
    return MeasureDiff(findings=tuple(findings), renames=renames)


def _measures_by_table(model: SemanticModel) -> dict[str, tuple[Measure, ...]]:
    """Measures per table name, merging tables declared in several files."""
    merged: dict[str, tuple[Measure, ...]] = {}
    for table in model.tables:
        merged[table.name] = (*merged.get(table.name, ()), *table.measures)
    return merged


def _unparsed_measures(model: SemanticModel) -> set[str]:
    """``Table[Name]`` keys of the measures that could not be parsed."""
    return {i.measure for i in model.issues if i.measure}


class _TableDiff(NamedTuple):
    """Findings and renames within one table, and its unpaired measures."""

    findings: list[Finding]
    renames: dict[str, str]
    removed: list[Measure]
    added: list[Measure]


def _diff_table(
    table: str,
    old: tuple[Measure, ...],
    new: tuple[Measure, ...],
    unparsed: set[str],
) -> _TableDiff:
    old_by_name = {m.name: m for m in old}
    new_by_name = {m.name: m for m in new}
    removed = [
        m
        for m in old
        if m.name not in new_by_name and field_key(table, m.name) not in unparsed
    ]
    added = [
        m
        for m in new
        if m.name not in old_by_name and field_key(table, m.name) not in unparsed
    ]
    pairs = _renamed_pairs(removed, added)
    renamed_old = {o.name for o, _ in pairs}
    renamed_new = {n.name for _, n in pairs}
    findings = [_renamed(table, o, n) for o, n in pairs]
    findings += [
        _modified(table, old_by_name[name], new_by_name[name])
        for name in sorted(old_by_name.keys() & new_by_name.keys())
        if old_by_name[name].expression != new_by_name[name].expression
    ]
    renames = {field_key(table, o.name): field_key(table, n.name) for o, n in pairs}
    return _TableDiff(
        findings=findings,
        renames=renames,
        removed=[m for m in removed if m.name not in renamed_old],
        added=[m for m in added if m.name not in renamed_new],
    )


def _moved_pairs(
    removed: list[TableMeasure], added: list[TableMeasure]
) -> list[tuple[TableMeasure, TableMeasure]]:
    """Pair measures that left one table and appear unchanged in another.

    Name and expression must both match, and the pair must be unique.
    """
    removed_by = unique_by(removed, _name_and_expression)
    added_by = unique_by(added, _name_and_expression)
    shared = sorted(removed_by.keys() & added_by.keys())
    return [(removed_by[k], added_by[k]) for k in shared]


def _name_and_expression(item: TableMeasure) -> str:
    """A key equal for measures with the same name and expression."""
    _, measure = item
    return f"{measure.name}\0{measure.expression}"


def _renamed_pairs(
    removed: list[Measure], added: list[Measure]
) -> list[tuple[Measure, Measure]]:
    """Pair removed and added measures whose expression is unique and equal."""
    removed_by_expr = unique_by(removed, _expression)
    added_by_expr = unique_by(added, _expression)
    shared = sorted(removed_by_expr.keys() & added_by_expr.keys())
    return [(removed_by_expr[e], added_by_expr[e]) for e in shared]


def _expression(measure: Measure) -> str:
    return measure.expression


def _path(table: str, name: str) -> str:
    return f"{MODEL_PATH}/{table}/{name}"


def _renamed(table: str, old: Measure, new: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.RENAMED,
        path=_path(table, old.name),
        message=f"Measure {table}[{old.name}] renamed to {table}[{new.name}]",
        old=old.name,
        new=new.name,
        old_location=old.location,
        new_location=new.location,
    )


def _moved(old: TableMeasure, new: TableMeasure) -> Finding:
    (old_table, measure), (new_table, moved) = old, new
    return make_finding(
        Category.MEASURE,
        ChangeKind.MOVED,
        path=_path(old_table, measure.name),
        message=f"Measure {old_table}[{measure.name}] moved to "
        f"{new_table}[{moved.name}]",
        old=old_table,
        new=new_table,
        old_location=measure.location,
        new_location=moved.location,
    )


def _removed(table: str, measure: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.REMOVED,
        path=_path(table, measure.name),
        message=f"Measure {table}[{measure.name}] removed",
        old=measure.expression,
        old_location=measure.location,
    )


def _added(table: str, measure: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.ADDED,
        path=_path(table, measure.name),
        message=f"Measure {table}[{measure.name}] added",
        new=measure.expression,
        new_location=measure.location,
    )


def _modified(table: str, old: Measure, new: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.MODIFIED,
        path=_path(table, old.name),
        message=f"Expression of measure {table}[{old.name}] changed",
        old=old.expression,
        new=new.expression,
        old_location=old.location,
        new_location=new.location,
    )
