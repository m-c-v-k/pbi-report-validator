"""Parse PBIR filter cards and slicer selections.

Filter conditions are stored in PBIR as small query-language trees
(``From`` + ``Where``). They are parsed into structured ``Condition``
models (used to build DAX) and rendered from those to a normalised,
readable string such as ``Product[Category] in ('Bikes', 'Clothing')``,
which is what the diff compares and the reports show. Rendering from the
structured form keeps the two in agreement.
"""

import re
from typing import Any, Literal, NamedTuple, assert_never, cast

from pbi_report_validator.domain.models import (
    AllCondition,
    BinaryCondition,
    ComparisonCondition,
    Condition,
    FieldRef,
    Filter,
    FilterLevel,
    InCondition,
    LiteralKind,
    LiteralValue,
    NotCondition,
    SlicerState,
    TopNCondition,
)
from pbi_report_validator.parsers.pbir_fields import parse_field
from pbi_report_validator.parsers.quoting import is_quoted, unquote

Operator = Literal["=", ">", ">=", "<", "<="]
COMPARISON_OPERATORS: dict[int, Operator] = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}
Direction = Literal["top", "bottom"]
# The sort direction of a TopN subquery: descending keeps the top values.
TOP_N_DIRECTIONS: dict[int, Direction] = {1: "bottom", 2: "top"}
# The L/D/M type suffix (integer/decimal/currency) is dropped: DAX number
# literals do not need it, and the text form never showed it.
NUMBER_LITERAL = re.compile(r"^(-?\d+(?:\.\d+)?)[LDM]?$")
DATETIME_LITERAL = re.compile(r"^datetime'(?P<value>[^']*)'$")


class UnsupportedConditionError(ValueError):
    """A filter condition uses a construct the parser does not know."""


class _Sources(NamedTuple):
    """What a query's ``From`` list declares, by alias."""

    tables: dict[str, str]
    subqueries: dict[str, dict[str, Any]]


def parse_filters(
    container: Any, level: FilterLevel
) -> tuple[tuple[Filter, ...], list[str]]:
    """Parse the ``filterConfig`` of a report, page or visual.

    Args:
        container: The JSON object that may hold ``filterConfig``.
        level: Where the filters are defined.

    Returns:
        The filters in file order, and a message for each filter that could
        not be fully parsed. Such filters are still returned, with
        ``condition=None``.
    """
    config = container.get("filterConfig") if isinstance(container, dict) else None
    entries = config.get("filters", []) if isinstance(config, dict) else []
    filters: list[Filter] = []
    problems: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            parsed, problem = _parse_filter(entry, level)
            filters.append(parsed)
            problems += [problem] if problem else []
    return tuple(filters), problems


def parse_slicer_state(
    body: dict[str, Any], field_hint: FieldRef | None
) -> tuple[SlicerState | None, list[str]]:
    """Parse the selection stored in a slicer's ``objects.general`` filter.

    Args:
        body: The ``visual`` object of a slicer.
        field_hint: The slicer's field, used when the selection itself names
            no field.

    Returns:
        The slicer state (``None`` if the visual is not a slicer), and a
        message if the selection could not be parsed.
    """
    if body.get("visualType") != "slicer":
        return None, []
    expression, problem = _parse_or_problem(_slicer_query(body), "slicer selection")
    state = SlicerState(
        field=field_hint,
        condition=render(expression) if expression else None,
        expression=expression,
    )
    return state, [problem] if problem else []


def render_condition(query: Any) -> str | None:
    """Render a PBIR filter query (``From``/``Where``) as text.

    Returns:
        The condition, or ``None`` if the query has no ``Where`` clause.

    Raises:
        UnsupportedConditionError: The query uses an unknown construct.
    """
    expression = parse_condition(query)
    return render(expression) if expression else None


def parse_condition(query: Any) -> Condition | None:
    """Parse a PBIR filter query (``From``/``Where``) into a ``Condition``.

    Returns:
        The condition, or ``None`` if the query has no ``Where`` clause. A
        single ``Where`` item is returned as is; several are wrapped in an
        ``AllCondition``.

    Raises:
        UnsupportedConditionError: The query uses an unknown construct.
    """
    if not isinstance(query, dict):
        return None
    sources = _sources(query.get("From"))
    where = query.get("Where")
    if not isinstance(where, list) or not where:
        return None
    items = tuple(
        _condition(item.get("Condition") if isinstance(item, dict) else None, sources)
        for item in where
    )
    return items[0] if len(items) == 1 else AllCondition(items=items)


def render(condition: Condition) -> str:
    """Render a structured condition as normalised text."""
    if isinstance(condition, InCondition):
        return _render_in(condition)
    if isinstance(condition, ComparisonCondition):
        value = render_literal(condition.value)
        return f"{condition.field.key} {condition.operator} {value}"
    if isinstance(condition, TopNCondition):
        return _render_top_n(condition)
    if isinstance(condition, NotCondition):
        return f"not ({render(condition.operand)})"
    if isinstance(condition, BinaryCondition):
        left, right = render(condition.left), render(condition.right)
        return f"({left}) {condition.kind} ({right})"
    if isinstance(condition, AllCondition):
        return " and ".join(
            f"({render(item)})" if isinstance(item, BinaryCondition) else render(item)
            for item in condition.items
        )
    assert_never(condition)


def render_literal(literal: LiteralValue) -> str:
    """Render a literal the way it appears in a normalised condition."""
    if literal.kind == LiteralKind.TEXT:
        return "'" + literal.value.replace("'", "''") + "'"
    if literal.kind == LiteralKind.DATETIME:
        return f"datetime'{literal.value}'"
    if literal.kind == LiteralKind.NULL:
        return "null"
    return literal.value


def parse_literal(raw: str) -> LiteralValue:
    """Classify a raw PBIR literal such as ``2025L``, ``'Bikes'`` or ``true``."""
    number = NUMBER_LITERAL.match(raw)
    if number:
        return LiteralValue(kind=LiteralKind.NUMBER, value=number.group(1))
    if is_quoted(raw):
        return LiteralValue(kind=LiteralKind.TEXT, value=unquote(raw))
    if raw in ("true", "false"):
        return LiteralValue(kind=LiteralKind.BOOLEAN, value=raw)
    if raw == "null":
        return LiteralValue(kind=LiteralKind.NULL, value="")
    datetime = DATETIME_LITERAL.match(raw)
    if datetime:
        return LiteralValue(kind=LiteralKind.DATETIME, value=datetime["value"])
    return LiteralValue(kind=LiteralKind.OTHER, value=raw)


def _render_in(condition: InCondition) -> str:
    fields = [f.key for f in condition.fields]
    values = [", ".join(render_literal(v) for v in row) for row in condition.rows]
    target = fields[0] if len(fields) == 1 else f"({', '.join(fields)})"
    rendered = values if len(fields) == 1 else [f"({v})" for v in values]
    return f"{target} in ({', '.join(rendered)})"


def _render_top_n(condition: TopNCondition) -> str:
    order = condition.order_by
    by = f"{order.aggregation}({order.key})" if order.aggregation else order.key
    limit = f"{condition.direction} {condition.count}"
    return f"{condition.field.key} {limit} by {by}"


def _parse_filter(
    entry: dict[str, Any], level: FilterLevel
) -> tuple[Filter, str | None]:
    name = str(entry.get("name", ""))
    expression, problem = _parse_or_problem(entry.get("filter"), f"filter {name}")
    parsed = Filter(
        name=name,
        level=level,
        field=parse_field(entry.get("field")),
        filter_type=str(entry.get("type", "Unknown")),
        condition=render(expression) if expression else None,
        expression=expression,
    )
    return parsed, problem


def _parse_or_problem(query: Any, label: str) -> tuple[Condition | None, str | None]:
    """The condition, or ``None`` and why it is not supported."""
    try:
        return parse_condition(query), None
    except UnsupportedConditionError as exc:
        return None, f"{label}: unsupported condition ({exc})"


def _slicer_query(body: dict[str, Any]) -> Any:
    try:
        return body["objects"]["general"][0]["properties"]["filter"]["filter"]
    except (KeyError, IndexError, TypeError):
        return None


def _aliases(sources: Any) -> dict[str, str]:
    if not isinstance(sources, list):
        return {}
    return {
        s["Name"]: s["Entity"]
        for s in sources
        if isinstance(s, dict)
        and isinstance(s.get("Name"), str)
        and isinstance(s.get("Entity"), str)
    }


def _sources(sources: Any) -> _Sources:
    subqueries = {}
    for source in sources if isinstance(sources, list) else []:
        query = _subquery_of(source)
        if query is not None:
            subqueries[source.get("Name")] = query
    return _Sources(_aliases(sources), subqueries)


def _subquery_of(source: Any) -> dict[str, Any] | None:
    try:
        query = source["Expression"]["Subquery"]["Query"]
    except (KeyError, TypeError):
        return None
    return query if isinstance(query, dict) else None


def _condition(node: Any, sources: _Sources) -> Condition:
    if not isinstance(node, dict) or len(node) != 1:
        raise UnsupportedConditionError("malformed condition")
    kind, body = next(iter(node.items()))
    if not isinstance(body, dict):
        raise UnsupportedConditionError(kind)
    if kind == "In":
        return _in(body, sources)
    if kind == "Not":
        return NotCondition(operand=_condition(body.get("Expression"), sources))
    if kind in ("And", "Or"):
        return BinaryCondition(
            kind=cast(Literal["and", "or"], kind.lower()),
            left=_condition(body.get("Left"), sources),
            right=_condition(body.get("Right"), sources),
        )
    if kind == "Comparison":
        return _comparison(body, sources.tables)
    raise UnsupportedConditionError(kind)


def _in(body: dict[str, Any], sources: _Sources) -> InCondition | TopNCondition:
    expressions = body.get("Expressions", [])
    if "Table" in body:
        return _top_n(expressions, body["Table"], sources)
    rows = body.get("Values", [])
    if (
        not isinstance(expressions, list)
        or not isinstance(rows, list)
        or not expressions
        or not rows
    ):
        raise UnsupportedConditionError("In")
    if any(not isinstance(row, list) or len(row) != len(expressions) for row in rows):
        raise UnsupportedConditionError("In with rows that do not match its fields")
    return InCondition(
        fields=tuple(_field(e, sources.tables) for e in expressions),
        rows=tuple(tuple(_literal(v) for v in row) for row in rows),
    )


def _top_n(expressions: Any, table: Any, sources: _Sources) -> TopNCondition:
    """An ``In`` over a subquery; only the TopN form of a subquery is known."""
    query = _referenced_subquery(table, sources)
    count = query.get("Top")
    order_by = query.get("OrderBy")
    if (
        not isinstance(expressions, list)
        or len(expressions) != 1
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        or not isinstance(order_by, list)
        or len(order_by) != 1
        or not isinstance(order_by[0], dict)
    ):
        raise UnsupportedConditionError("In with a subquery")
    direction = order_by[0].get("Direction")
    limit = TOP_N_DIRECTIONS.get(direction) if isinstance(direction, int) else None
    if limit is None:
        raise UnsupportedConditionError("In with a subquery")
    inner = _sources(query.get("From")).tables
    return TopNCondition(
        field=_field(expressions[0], sources.tables),
        direction=limit,
        count=count,
        order_by=_field(order_by[0].get("Expression"), inner),
    )


def _referenced_subquery(table: Any, sources: _Sources) -> dict[str, Any]:
    reference = table.get("SourceRef") if isinstance(table, dict) else None
    alias = reference.get("Source") if isinstance(reference, dict) else None
    query = sources.subqueries.get(alias) if isinstance(alias, str) else None
    if query is None:
        raise UnsupportedConditionError("In with a subquery")
    return query


def _comparison(body: dict[str, Any], aliases: dict[str, str]) -> ComparisonCondition:
    kind = body.get("ComparisonKind")
    operator = COMPARISON_OPERATORS.get(kind) if isinstance(kind, int) else None
    if operator is None:
        raise UnsupportedConditionError("ComparisonKind")
    return ComparisonCondition(
        field=_field(body.get("Left"), aliases),
        operator=operator,
        value=_literal(body.get("Right")),
    )


def _field(expression: Any, aliases: dict[str, str]) -> FieldRef:
    field = parse_field(expression, aliases)
    if field is None:
        raise UnsupportedConditionError("unrecognised field")
    return field


def _literal(node: Any) -> LiteralValue:
    literal = node.get("Literal") if isinstance(node, dict) else None
    value = literal.get("Value") if isinstance(literal, dict) else None
    if not isinstance(value, str):
        raise UnsupportedConditionError("non-literal value")
    return parse_literal(value)
