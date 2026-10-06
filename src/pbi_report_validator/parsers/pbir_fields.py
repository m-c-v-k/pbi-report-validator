"""Turn PBIR field expressions into ``FieldRef`` models.

PBIR stores field references as nested query-language objects, e.g.
``{"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}},
"Property": "Total Sales"}}``. Filters use the same shape but refer to an
alias (``{"SourceRef": {"Source": "s"}}``) declared in their ``From`` list.
"""

from collections.abc import Mapping
from typing import Any

from pbi_report_validator.domain.models import FieldKind, FieldRef

AGGREGATION_FUNCTIONS = {
    0: "Sum",
    1: "Avg",
    2: "DistinctCount",
    3: "Min",
    4: "Max",
    5: "Count",
    6: "Median",
    7: "StandardDeviation",
    8: "Variance",
}


def parse_field(
    expression: Any, aliases: Mapping[str, str] | None = None
) -> FieldRef | None:
    """Convert a PBIR field expression to a ``FieldRef``.

    Args:
        expression: The field object (``Column``, ``Measure``, ``Aggregation``
            or ``HierarchyLevel``).
        aliases: Source alias to table name, for expressions inside filters.

    Returns:
        The field reference, or ``None`` if the expression is not a
        recognised field.
    """
    if not isinstance(expression, dict):
        return None
    aliases = aliases or {}
    if "Column" in expression or "Measure" in expression:
        kind = FieldKind.COLUMN if "Column" in expression else FieldKind.MEASURE
        body = expression.get("Column") or expression.get("Measure")
        return _property_field(body, kind, aliases)
    if "Aggregation" in expression:
        return _aggregation_field(expression["Aggregation"], aliases)
    if "HierarchyLevel" in expression:
        return _hierarchy_level_field(expression["HierarchyLevel"], aliases)
    return None


def _property_field(
    body: Any, kind: FieldKind, aliases: Mapping[str, str]
) -> FieldRef | None:
    if not isinstance(body, dict):
        return None
    table = _table(body.get("Expression"), aliases)
    name = body.get("Property")
    if table is None or not isinstance(name, str):
        return None
    return FieldRef(table=table, name=name, kind=kind)


def _aggregation_field(body: Any, aliases: Mapping[str, str]) -> FieldRef | None:
    if not isinstance(body, dict):
        return None
    inner = parse_field(body.get("Expression"), aliases)
    if inner is None:
        return None
    function = body.get("Function")
    aggregation = (
        AGGREGATION_FUNCTIONS.get(function, str(function))
        if isinstance(function, int)
        else str(function)
    )
    return FieldRef(
        table=inner.table,
        name=inner.name,
        kind=FieldKind.AGGREGATION,
        aggregation=aggregation,
    )


def _hierarchy_level_field(body: Any, aliases: Mapping[str, str]) -> FieldRef | None:
    if not isinstance(body, dict):
        return None
    hierarchy = body.get("Expression", {}).get("Hierarchy", {})
    if not isinstance(hierarchy, dict):
        return None
    table = _table(hierarchy.get("Expression"), aliases)
    name = hierarchy.get("Hierarchy")
    level = body.get("Level")
    if table is None or not isinstance(name, str) or not isinstance(level, str):
        return None
    return FieldRef(table=table, name=f"{name}.{level}", kind=FieldKind.HIERARCHY_LEVEL)


def _table(expression: Any, aliases: Mapping[str, str]) -> str | None:
    if not isinstance(expression, dict):
        return None
    source = expression.get("SourceRef", {})
    if not isinstance(source, dict):
        return None
    entity = source.get("Entity")
    if isinstance(entity, str):
        return entity
    alias = source.get("Source")
    return aliases.get(alias) if isinstance(alias, str) else None
