"""Render filter conditions as text, and rename the fields they use.

The rendered form (``Product[Category] in ('Bikes', 'Clothing')``) is what
the diff compares and the reports show. Renaming works on the structured
condition, so a key is only replaced where it really is a field reference.
"""

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import assert_never

from pbi_report_validator.domain.helpers import field_name
from pbi_report_validator.domain.report import (
    AllCondition,
    BinaryCondition,
    ComparisonCondition,
    Condition,
    FieldRef,
    InCondition,
    LiteralKind,
    LiteralValue,
    NotCondition,
    TopNCondition,
)


def render(condition: Condition) -> str:
    """Render a structured condition as normalised text."""
    if isinstance(condition, InCondition):
        return _render_in(condition)
    if isinstance(condition, ComparisonCondition):
        value = render_literal(condition.value)
        return f"{condition.field.aggregated_key} {condition.operator} {value}"
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


def rename_fields(condition: Condition, renames: Mapping[str, str]) -> Condition:
    """The condition with every field whose key is in ``renames`` renamed.

    Each reference is looked up once, so chained renames (A to B, B to C)
    are not applied twice. Renames stay within a table, so only the name
    changes.
    """
    if isinstance(condition, InCondition):
        fields = tuple(_renamed(f, renames) for f in condition.fields)
        return condition.model_copy(update={"fields": fields})
    if isinstance(condition, ComparisonCondition):
        return condition.model_copy(
            update={"field": _renamed(condition.field, renames)}
        )
    if isinstance(condition, TopNCondition):
        return condition.model_copy(
            update={
                "field": _renamed(condition.field, renames),
                "order_by": _renamed(condition.order_by, renames),
            }
        )
    if isinstance(condition, NotCondition):
        operand = rename_fields(condition.operand, renames)
        return condition.model_copy(update={"operand": operand})
    if isinstance(condition, BinaryCondition):
        left = rename_fields(condition.left, renames)
        right = rename_fields(condition.right, renames)
        return condition.model_copy(update={"left": left, "right": right})
    if isinstance(condition, AllCondition):
        items = tuple(rename_fields(item, renames) for item in condition.items)
        return condition.model_copy(update={"items": items})
    assert_never(condition)


def _renamed(field: FieldRef, renames: Mapping[str, str]) -> FieldRef:
    new_key = renames.get(field.key)
    if new_key is None:
        return field
    return field.model_copy(update={"name": field_name(new_key)})


def _render_in(condition: InCondition) -> str:
    """Render ``in`` with its rows sorted, since the order selects nothing.

    PBIR keeps values in the order they were picked, so the same selection
    picked in another order must render the same.
    """
    fields = [f.aggregated_key for f in condition.fields]
    rows = sorted(set(condition.rows), key=_row_sort_key)
    values = [", ".join(render_literal(v) for v in row) for row in rows]
    target = fields[0] if len(fields) == 1 else f"({', '.join(fields)})"
    rendered = values if len(fields) == 1 else [f"({v})" for v in values]
    return f"{target} in ({', '.join(rendered)})"


def _row_sort_key(
    row: tuple[LiteralValue, ...],
) -> tuple[tuple[str, Decimal, str], ...]:
    return tuple(_literal_sort_key(v) for v in row)


def _literal_sort_key(literal: LiteralValue) -> tuple[str, Decimal, str]:
    """Kind first, then numbers by value and everything else by text."""
    is_number = literal.kind == LiteralKind.NUMBER
    number = _decimal_or_zero(literal.value) if is_number else Decimal(0)
    return (literal.kind.value, number, literal.value)


def _decimal_or_zero(value: str) -> Decimal:
    """The number, or zero when it is not a finite decimal (sorts by text)."""
    try:
        number = Decimal(value)
    except InvalidOperation:
        return Decimal(0)
    return number if number.is_finite() else Decimal(0)


def _render_top_n(condition: TopNCondition) -> str:
    limit = f"{condition.direction} {condition.count}"
    by = condition.order_by.aggregated_key
    return f"{condition.field.aggregated_key} {limit} by {by}"
