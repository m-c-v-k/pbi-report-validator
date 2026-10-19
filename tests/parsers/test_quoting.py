import pytest

from pbi_report_validator.parsers.quoting import is_quoted, unquote


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("'Total sales'", "Total sales"),
        ("'Sales ''24'", "Sales '24"),
        ("''", ""),
        ("Sales", "Sales"),
        ("'", "'"),
        ("'open", "'open"),
    ],
)
def test_unquote(value: str, expected: str) -> None:
    assert unquote(value) == expected


@pytest.mark.parametrize(
    ("value", "quoted"), [("'a'", True), ("'", False), ("a", False)]
)
def test_is_quoted(value: str, quoted: bool) -> None:
    assert is_quoted(value) is quoted
