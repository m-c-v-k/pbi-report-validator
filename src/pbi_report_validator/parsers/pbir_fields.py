"""Turn PBIR field expressions into ``FieldRef`` models.

PBIR stores field references as nested query-language objects, e.g.
``{"Measure": {"Expression": {"SourceRef": {"Entity": "Sales"}},
"Property": "Total Sales"}}``. Filters use the same shape but refer to an
alias (``{"SourceRef": {"Source": "s"}}``) declared in their ``From`` list.
"""

import hashlib
import json
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
    if "Column" in expression:
        return _property_field(expression["Column"], FieldKind.COLUMN, aliases)
    if "Measure" in expression:
        return _property_field(expression["Measure"], FieldKind.MEASURE, aliases)
    if "Aggregation" in expression:
        return _aggregation_field(expression["Aggregation"], aliases)
    if "HierarchyLevel" in expression:
        return _hierarchy_level_field(expression["HierarchyLevel"], aliases)
    return None


def unknown_field(expression: Any) -> FieldRef | None:
    """A field of a kind this tool cannot read, so it is still compared.

    The name is the expression's type and a short hash of its JSON, e.g.
    ``NativeVisualCalculation 3fa2c1d0``: any edit to it changes the name.

    Returns:
        The field, or ``None`` if ``expression`` is not a non-empty object.
    """
    if not isinstance(expression, dict) or not expression:
        return None
    canonical = json.dumps(expression, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode()).hexdigest()[:8]
    kind = next(iter(sorted(expression)))
    return FieldRef(table="", name=f"{kind} {digest}", kind=FieldKind.UNKNOWN)


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
    """Aggregated column; the aggregated field's own kind is not kept."""
    if not isinstance(body, dict):
        return None
    inner = parse_field(body.get("Expression"), aliases)
    if inner is None:
        return None
    return FieldRef(
        table=inner.table,
        name=inner.name,
        kind=FieldKind.AGGREGATION,
        aggregation=_aggregation_name(body.get("Function")),
    )


def _aggregation_name(function: Any) -> str | None:
    if isinstance(function, bool) or function is None:
        return None
    if isinstance(function, int):
        return AGGREGATION_FUNCTIONS.get(function, str(function))
    return str(function)


def _hierarchy_level_field(body: Any, aliases: Mapping[str, str]) -> FieldRef | None:
    if not isinstance(body, dict):
        return None
    expression = body.get("Expression")
    hierarchy = expression.get("Hierarchy") if isinstance(expression, dict) else None
    if not isinstance(hierarchy, dict):
        return None
    table, prefix = _hierarchy_source(hierarchy.get("Expression"), aliases)
    name = hierarchy.get("Hierarchy")
    level = body.get("Level")
    if table is None or not isinstance(name, str) or not isinstance(level, str):
        return None
    return FieldRef(
        table=table, name=f"{prefix}{name}.{level}", kind=FieldKind.HIERARCHY_LEVEL
    )


def _hierarchy_source(
    expression: Any, aliases: Mapping[str, str]
) -> tuple[str | None, str]:
    """The hierarchy's table, and a name prefix for an auto date/time column.

    Auto date/time hierarchies hang off a date column through a
    ``PropertyVariationSource``, so the column name becomes part of the field
    name: ``Order Date.Date Hierarchy.Month``.
    """
    variation = (
        expression.get("PropertyVariationSource")
        if isinstance(expression, dict)
        else None
    )
    if not isinstance(variation, dict):
        return _table(expression, aliases), ""
    column = variation.get("Property")
    if not isinstance(column, str):
        return None, ""
    return _table(variation.get("Expression"), aliases), f"{column}."


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
