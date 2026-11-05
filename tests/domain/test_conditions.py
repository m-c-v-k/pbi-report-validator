import pytest

from pbi_report_validator.domain.conditions import rename_fields
from pbi_report_validator.domain.models import (
    ComparisonCondition,
    FieldKind,
    FieldRef,
    LiteralKind,
    LiteralValue,
)
from pbi_report_validator.domain.semantic import renamed_key
from tests import factories


def above_zero(table: str, name: str) -> ComparisonCondition:
    return ComparisonCondition(
        field=FieldRef(table=table, name=name, kind=FieldKind.MEASURE),
        operator=">",
        value=LiteralValue(kind=LiteralKind.NUMBER, value="0"),
    )


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (("Sales [EUR]", "Margin"), ("Sales [EUR]", "Gross Margin")),
        (("Sales", "Rate [%]"), ("Measures [x]", "Rate [%]")),
    ],
)
def test_renamed_field_keeps_table_and_name_with_brackets(
    old: tuple[str, str], new: tuple[str, str]
) -> None:
    renames = factories.renames((*old, *new))

    renamed = rename_fields(above_zero(*old), renames)

    assert renamed == above_zero(*new)


def test_renamed_key_falls_back_to_the_key() -> None:
    renames = factories.renames(("Sales [EUR]", "Margin", "Sales [EUR]", "Gross"))

    assert renamed_key("Sales [EUR][Margin]", renames) == "Sales [EUR][Gross]"
    assert renamed_key("Sales[Other]", renames) == "Sales[Other]"
