import pytest

from pbi_report_validator.domain.helpers import (
    field_key,
    field_name,
    is_within,
    unique_by,
    visual_path,
    visual_path_of,
)


def test_visual_path_round_trip() -> None:
    path = visual_path("overview", "card_total_sales")

    assert path == "overview/card_total_sales"
    assert visual_path_of(f"{path}/filters/f1") == path
    assert visual_path_of("overview") == "overview"


@pytest.mark.parametrize(
    ("path", "parent", "inside"),
    [
        ("overview/card", "overview/card", True),
        ("overview/card/fields/x", "overview/card", True),
        ("overview/card_2", "overview/card", False),
        ("overview", "overview/card", False),
    ],
)
def test_is_within(path: str, parent: str, inside: bool) -> None:
    assert is_within(path, parent) is inside


def test_field_key_and_name() -> None:
    key = field_key("Sales", "Margin %")

    assert key == "Sales[Margin %]"
    assert field_name(key) == "Margin %"


def test_unique_by_drops_duplicate_keys() -> None:
    items = ["apple", "avocado", "banana", "cherry", "cranberry", "date"]

    assert unique_by(items, lambda s: s[0]) == {"b": "banana", "d": "date"}
