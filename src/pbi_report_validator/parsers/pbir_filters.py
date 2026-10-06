"""Parse PBIR filter cards and slicer selections.

Filter conditions are stored in PBIR as small query-language trees
(``From`` + ``Where``). They are rendered to a normalised, readable string
such as ``Product[Category] in ('Bikes', 'Clothing')`` so two versions can
be compared as text and shown in reports.
"""

from typing import Any

from pbi_report_validator.domain.models import Filter, FilterLevel, SlicerState
from pbi_report_validator.parsers.pbir_fields import parse_field

COMPARISON_OPERATORS = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}
NUMBER_SUFFIXES = ("L", "D", "M")


class UnsupportedConditionError(ValueError):
    """A filter condition uses a construct the renderer does not know."""


def parse_filters(
    container: Any, level: FilterLevel, problems: list[str]
) -> tuple[Filter, ...]:
    """Parse the ``filterConfig`` of a report, page or visual.

    Args:
        container: The JSON object that may hold ``filterConfig``.
        level: Where the filters are defined.
        problems: Receives a message for each filter that could not be fully
            parsed. Such filters are still returned, with ``condition=None``.

    Returns:
        The filters in file order.
    """
    config = container.get("filterConfig") if isinstance(container, dict) else None
    entries = config.get("filters", []) if isinstance(config, dict) else []
    filters = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            filters.append(_parse_filter(entry, level, problems))
    return tuple(filters)


def parse_slicer_state(
    body: dict[str, Any], field_hint: Any, problems: list[str]
) -> SlicerState | None:
    """Parse the selection stored in a slicer's ``objects.general`` filter.

    Args:
        body: The ``visual`` object of a slicer.
        field_hint: The slicer's field (``FieldRef``), used when the selection
            itself names no field.
        problems: Receives a message if the selection could not be rendered.

    Returns:
        The slicer state, or ``None`` if the visual is not a slicer.
    """
    if body.get("visualType") != "slicer":
        return None
    query = _slicer_query(body)
    condition = _render_or_problem(query, "slicer selection", problems)
    return SlicerState(field=field_hint, condition=condition)


def render_condition(query: Any) -> str | None:
    """Render a PBIR filter query (``From``/``Where``) as text.

    Returns:
        The condition, or ``None`` if the query has no ``Where`` clause.

    Raises:
        UnsupportedConditionError: The query uses an unknown construct.
    """
    if not isinstance(query, dict):
        return None
    aliases = _aliases(query.get("From"))
    where = query.get("Where")
    if not isinstance(where, list) or not where:
        return None
    conditions = [
        item.get("Condition") if isinstance(item, dict) else None for item in where
    ]
    parts = [_condition(c, aliases) for c in conditions]
    if len(parts) > 1:
        parts = [
            f"({part})" if _is_compound(c) else part
            for part, c in zip(parts, conditions, strict=True)
        ]
    return " and ".join(parts)


def _is_compound(node: Any) -> bool:
    return isinstance(node, dict) and ("And" in node or "Or" in node)


def _parse_filter(
    entry: dict[str, Any], level: FilterLevel, problems: list[str]
) -> Filter:
    name = str(entry.get("name", ""))
    condition = _render_or_problem(entry.get("filter"), f"filter {name}", problems)
    return Filter(
        name=name,
        level=level,
        field=parse_field(entry.get("field")),
        filter_type=str(entry.get("type", "Unknown")),
        condition=condition,
    )


def _render_or_problem(query: Any, label: str, problems: list[str]) -> str | None:
    try:
        return render_condition(query)
    except UnsupportedConditionError as exc:
        problems.append(f"{label}: unsupported condition ({exc})")
        return None


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


def _condition(node: Any, aliases: dict[str, str]) -> str:
    if not isinstance(node, dict) or len(node) != 1:
        raise UnsupportedConditionError("malformed condition")
    kind, body = next(iter(node.items()))
    if not isinstance(body, dict):
        raise UnsupportedConditionError(kind)
    if kind == "In":
        return _in(body, aliases)
    if kind == "Not":
        return f"not ({_condition(body.get('Expression'), aliases)})"
    if kind in ("And", "Or"):
        left = _condition(body.get("Left"), aliases)
        right = _condition(body.get("Right"), aliases)
        return f"({left}) {kind.lower()} ({right})"
    if kind == "Comparison":
        return _comparison(body, aliases)
    raise UnsupportedConditionError(kind)


def _in(body: dict[str, Any], aliases: dict[str, str]) -> str:
    expressions = body.get("Expressions", [])
    rows = body.get("Values", [])
    if not isinstance(expressions, list) or not isinstance(rows, list):
        raise UnsupportedConditionError("In")
    fields = [_field_key(e, aliases) for e in expressions]
    values = [", ".join(_literal(v) for v in row) for row in rows]
    target = fields[0] if len(fields) == 1 else f"({', '.join(fields)})"
    rendered = values if len(fields) == 1 else [f"({v})" for v in values]
    return f"{target} in ({', '.join(rendered)})"


def _comparison(body: dict[str, Any], aliases: dict[str, str]) -> str:
    kind = body.get("ComparisonKind")
    operator = COMPARISON_OPERATORS.get(kind) if isinstance(kind, int) else None
    if operator is None:
        raise UnsupportedConditionError("ComparisonKind")
    left = _field_key(body.get("Left"), aliases)
    return f"{left} {operator} {_literal(body.get('Right'))}"


def _field_key(expression: Any, aliases: dict[str, str]) -> str:
    field = parse_field(expression, aliases)
    if field is None:
        raise UnsupportedConditionError("unrecognised field")
    return field.key


def _literal(node: Any) -> str:
    value = node.get("Literal", {}).get("Value") if isinstance(node, dict) else None
    if not isinstance(value, str):
        raise UnsupportedConditionError("non-literal value")
    if value.endswith(NUMBER_SUFFIXES) and _is_number(value[:-1]):
        return value[:-1]
    return value


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
