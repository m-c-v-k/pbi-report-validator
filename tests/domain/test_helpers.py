import pytest

from pbi_report_validator.domain.helpers import (
    field_key,
    finding_key,
    is_within,
    numbered_keys,
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


def test_field_key() -> None:
    assert field_key("Sales", "Margin %") == "Sales[Margin %]"


def test_unique_by_drops_duplicate_keys() -> None:
    items = ["apple", "avocado", "banana", "cherry", "cranberry", "date"]

    assert unique_by(items, lambda s: s[0]) == {"b": "banana", "d": "date"}


def test_finding_key_joins_its_parts() -> None:
    key = finding_key("model", "measure", "renamed", "model/Sales/Margin %")

    assert key == "model:measure:renamed:model/Sales/Margin %"


def test_only_repeated_keys_are_numbered() -> None:
    keys = ["a", "b", "a", "c", "a"]

    assert numbered_keys(keys) == ["a", "b", "a#2", "c", "a#3"]
