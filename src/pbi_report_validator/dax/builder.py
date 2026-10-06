"""Build a DAX query that returns what a visual shows.

Every supported visual becomes one query::

    EVALUATE
    SUMMARIZECOLUMNS(
        <group-by columns>,
        <one filter table per active filter or slicer selection>,
        "<name>", <measure or aggregation>, ...
    )
    ORDER BY <group-by columns>

The filter context is the report filters, the page filters, the visual's
own filters and the selections of the slicers on the same page. Anything
that cannot be translated faithfully gives an ``UnsupportedQuery`` with a
reason instead of a query that might return the wrong numbers.

Known limitations: slicer interactions edited in Power BI ("edit
interactions"), slicers synced from other pages and filter cards that
could not be parsed are not taken into account.
"""

from collections.abc import Sequence
from datetime import datetime

from pbi_report_validator.domain.models import (
    AllCondition,
    BinaryCondition,
    ComparisonCondition,
    Condition,
    DaxQuery,
    FieldKind,
    FieldRef,
    Filter,
    InCondition,
    LiteralKind,
    LiteralValue,
    NotCondition,
    Page,
    UnsupportedQuery,
    Visual,
)

QUERYABLE_TYPES = frozenset(
    {
        "card",
        "cardVisual",
        "multiRowCard",
        "tableEx",
        "pivotTable",
        "barChart",
        "columnChart",
        "clusteredBarChart",
        "clusteredColumnChart",
        "hundredPercentStackedBarChart",
        "hundredPercentStackedColumnChart",
        "lineChart",
        "areaChart",
        "stackedAreaChart",
        "lineClusteredColumnComboChart",
        "lineStackedColumnComboChart",
        "pieChart",
        "donutChart",
        "treemap",
        "funnel",
    }
)
AGGREGATIONS = {
    "Sum": "SUM",
    "Avg": "AVERAGE",
    "DistinctCount": "DISTINCTCOUNT",
    "Min": "MIN",
    "Max": "MAX",
    "Count": "COUNTA",
    "Median": "MEDIAN",
}
INDENT = "    "


class UnsupportedError(ValueError):
    """Part of a visual cannot be expressed as a faithful DAX query."""


def build_query(
    visual: Visual, page: Page, report_filters: Sequence[Filter]
) -> DaxQuery | UnsupportedQuery:
    """Build the query for one visual on a page.

    Args:
        visual: The visual to query.
        page: The page it is on (for page filters and slicers).
        report_filters: Filters that apply to every page.
    """
    try:
        return _build(visual, page, report_filters)
    except UnsupportedError as exc:
        return UnsupportedQuery(reason=str(exc))


def _build(visual: Visual, page: Page, report_filters: Sequence[Filter]) -> DaxQuery:
    if visual.slicer is not None:
        raise UnsupportedError("slicers only filter other visuals")
    if visual.visual_type not in QUERYABLE_TYPES:
        raise UnsupportedError(f"visual type {visual.visual_type} is not supported")
    group_by: list[str] = []
    values: list[tuple[str, str]] = []
    for projection in visual.projections:
        field = projection.field
        if field.kind == FieldKind.COLUMN:
            reference = column(field)
            if reference not in group_by:
                group_by.append(reference)
        else:
            values.append((_unique_name(field.name, values), _value(field)))
    if not group_by and not values:
        raise UnsupportedError("visual has no fields")
    filters = [_filter_table(c) for c in _conditions(visual, page, report_filters)]
    arguments = [
        *group_by,
        *filters,
        *(f"{text(name)}, {expr}" for name, expr in values),
    ]
    lines = ["EVALUATE", "SUMMARIZECOLUMNS("]
    lines += [f"{INDENT}{argument}," for argument in arguments]
    lines[-1] = lines[-1].removesuffix(",")
    lines.append(")")
    if group_by:
        lines.append(f"ORDER BY {', '.join(group_by)}")
    return DaxQuery(
        dax="\n".join(lines),
        group_by=tuple(group_by),
        values=tuple(name for name, _ in values),
    )


def _conditions(
    visual: Visual, page: Page, report_filters: Sequence[Filter]
) -> list[Condition]:
    """Active conditions in scope, splitting ``AllCondition`` into its items."""
    filters = [*report_filters, *page.filters, *visual.filters]
    found = [f.expression for f in filters if f.expression is not None]
    found += [
        other.slicer.expression
        for other in page.visuals
        if other.name != visual.name and other.slicer and other.slicer.expression
    ]
    flat: list[Condition] = []
    for condition in found:
        flat += condition.items if isinstance(condition, AllCondition) else [condition]
    return flat


def _filter_table(condition: Condition) -> str:
    """A table expression that applies ``condition`` as a filter."""
    fields = _fields(condition)
    if any(f.kind != FieldKind.COLUMN for f in fields):
        raise UnsupportedError("filters on measures are not supported yet")
    if isinstance(condition, InCondition):
        rows = ", ".join(_row(r, len(condition.fields)) for r in condition.rows)
        targets = ", ".join(column(f) for f in condition.fields)
        return f"TREATAS({{{rows}}}, {targets})"
    if len({f.table for f in fields}) > 1:
        raise UnsupportedError("conditions across several tables are not supported")
    unique = list(dict.fromkeys(column(f) for f in fields))
    return f"FILTER(ALL({', '.join(unique)}), {_predicate(condition)})"


def _predicate(condition: Condition) -> str:
    """The condition as a boolean DAX expression."""
    if isinstance(condition, InCondition):
        rows = ", ".join(_row(r, len(condition.fields)) for r in condition.rows)
        targets = [column(f) for f in condition.fields]
        target = targets[0] if len(targets) == 1 else f"({', '.join(targets)})"
        return f"{target} IN {{{rows}}}"
    if isinstance(condition, ComparisonCondition):
        return (
            f"{column(condition.field)} {condition.operator} {literal(condition.value)}"
        )
    if isinstance(condition, NotCondition):
        return f"NOT({_predicate(condition.operand)})"
    if isinstance(condition, BinaryCondition):
        operator = "&&" if condition.kind == "and" else "||"
        return (
            f"({_predicate(condition.left)}) {operator} ({_predicate(condition.right)})"
        )
    return " && ".join(f"({_predicate(item)})" for item in condition.items)


def _fields(condition: Condition) -> list[FieldRef]:
    if isinstance(condition, InCondition):
        return list(condition.fields)
    if isinstance(condition, ComparisonCondition):
        return [condition.field]
    if isinstance(condition, NotCondition):
        return _fields(condition.operand)
    if isinstance(condition, BinaryCondition):
        return [*_fields(condition.left), *_fields(condition.right)]
    return [f for item in condition.items for f in _fields(item)]


def _row(values: Sequence[LiteralValue], width: int) -> str:
    rendered = ", ".join(literal(v) for v in values)
    return rendered if width == 1 else f"({rendered})"


def _value(field: FieldRef) -> str:
    if field.kind == FieldKind.MEASURE:
        return f"[{_escape_bracket(field.name)}]"
    if field.kind == FieldKind.AGGREGATION:
        function = AGGREGATIONS.get(field.aggregation or "")
        if function is None:
            raise UnsupportedError(f"aggregation {field.aggregation} is not supported")
        return f"{function}({column(field)})"
    raise UnsupportedError(f"{field.kind.value} fields are not supported yet")


def _unique_name(name: str, existing: Sequence[tuple[str, str]]) -> str:
    taken = {n for n, _ in existing}
    candidate, number = name, 2
    while candidate in taken:
        candidate, number = f"{name} ({number})", number + 1
    return candidate


def column(field: FieldRef) -> str:
    """A fully qualified column reference, e.g. ``'Sales'[Amount]``."""
    table = field.table.replace("'", "''")
    return f"'{table}'[{_escape_bracket(field.name)}]"


def text(value: str) -> str:
    """A DAX string literal."""
    return '"' + value.replace('"', '""') + '"'


def literal(value: LiteralValue) -> str:
    """A filter literal as DAX.

    Raises:
        UnsupportedError: The literal has no safe DAX equivalent.
    """
    if value.kind == LiteralKind.NUMBER:
        return value.value
    if value.kind == LiteralKind.TEXT:
        return text(value.value)
    if value.kind == LiteralKind.BOOLEAN:
        return value.value.upper()
    if value.kind == LiteralKind.NULL:
        return "BLANK()"
    if value.kind == LiteralKind.DATETIME:
        return _datetime(value.value)
    raise UnsupportedError(f"literal {value.value} is not supported")


def _datetime(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise UnsupportedError(f"date {value} is not supported") from exc
    date = f"DATE({moment.year}, {moment.month}, {moment.day})"
    if (moment.hour, moment.minute, moment.second) == (0, 0, 0):
        return date
    return f"{date} + TIME({moment.hour}, {moment.minute}, {moment.second})"


def _escape_bracket(name: str) -> str:
    return name.replace("]", "]]")
