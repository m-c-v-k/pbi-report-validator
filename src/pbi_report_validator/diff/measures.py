"""Diff the measures of two semantic model versions.

A measure that disappears from a table while a measure with the same
expression appears in the same table is reported once as a rename. The
resulting rename map lets the report diff ignore field references that
only changed because of that rename.

Limitation: a measure that is renamed *and* has its expression edited in
the same change cannot be recognised. It is reported as removed plus
added, and fields and filters that use it are reported as changed too.
"""

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


def diff_measures(old: SemanticModel | None, new: SemanticModel | None) -> MeasureDiff:
    """Compare measures table by table.

    Args:
        old: The old semantic model, or ``None`` if it was not available.
        new: The new semantic model, or ``None`` if it was not available.

    Returns:
        Added, removed, renamed and modified measures, and a map from old
        to new DAX key (``Sales[Margin %]`` -> ``Sales[Gross Margin %]``).
        Nothing is compared unless both models are available.
    """
    if old is None or new is None:
        return MeasureDiff()
    old_tables = {t.name: t.measures for t in old.tables}
    new_tables = {t.name: t.measures for t in new.tables}
    findings: list[Finding] = []
    renames: dict[str, str] = {}
    for table in sorted(old_tables.keys() | new_tables.keys()):
        table_findings, table_renames = _diff_table(
            table, old_tables.get(table, ()), new_tables.get(table, ())
        )
        findings += table_findings
        renames.update(table_renames)
    return MeasureDiff(findings=tuple(findings), renames=renames)


def _diff_table(
    table: str, old: tuple[Measure, ...], new: tuple[Measure, ...]
) -> tuple[list[Finding], dict[str, str]]:
    old_by_name = {m.name: m for m in old}
    new_by_name = {m.name: m for m in new}
    removed = [m for m in old if m.name not in new_by_name]
    added = [m for m in new if m.name not in old_by_name]
    pairs = _renamed_pairs(removed, added)
    renamed_old = {o.name for o, _ in pairs}
    renamed_new = {n.name for _, n in pairs}
    findings = [_renamed(table, o, n) for o, n in pairs]
    findings += [_removed(table, m) for m in removed if m.name not in renamed_old]
    findings += [_added(table, m) for m in added if m.name not in renamed_new]
    findings += [
        _modified(table, old_by_name[name], new_by_name[name])
        for name in sorted(old_by_name.keys() & new_by_name.keys())
        if old_by_name[name].expression != new_by_name[name].expression
    ]
    renames = {field_key(table, o.name): field_key(table, n.name) for o, n in pairs}
    return findings, renames


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
    )


def _removed(table: str, measure: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.REMOVED,
        path=_path(table, measure.name),
        message=f"Measure {table}[{measure.name}] removed",
        old=measure.expression,
    )


def _added(table: str, measure: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.ADDED,
        path=_path(table, measure.name),
        message=f"Measure {table}[{measure.name}] added",
        new=measure.expression,
    )


def _modified(table: str, old: Measure, new: Measure) -> Finding:
    return make_finding(
        Category.MEASURE,
        ChangeKind.MODIFIED,
        path=_path(table, old.name),
        message=f"Expression of measure {table}[{old.name}] changed",
        old=old.expression,
        new=new.expression,
    )
