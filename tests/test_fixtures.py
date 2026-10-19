import json
from pathlib import Path

import pytest

from pbi_report_validator.domain.models import Category, ChangeKind
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES

JSON_SUFFIXES = {".json", ".pbip", ".pbir", ".pbism"}
# Invalid on purpose: sales_v3 demonstrates the parse_issue finding.
BROKEN_ON_PURPOSE = (
    FIXTURES
    / "sales_v3/Sales.Report/definition/pages/overview/visuals/card_total_sales"
    / "visual.json"
)
JSON_FILES = sorted(
    p
    for p in FIXTURES.rglob("*")
    if p.is_file() and p.suffix in JSON_SUFFIXES and p != BROKEN_ON_PURPOSE
)


def test_fixtures_contain_json_files() -> None:
    assert JSON_FILES


@pytest.mark.parametrize(
    "path", JSON_FILES, ids=lambda p: p.relative_to(FIXTURES).as_posix()
)
def test_fixture_json_is_valid(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))


def test_broken_fixture_file_is_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(BROKEN_ON_PURPOSE.read_text(encoding="utf-8"))


def test_sales_v2_to_v3_reports_field_and_parse_issue() -> None:
    result = validate(FIXTURES / "sales_v2", FIXTURES / "sales_v3")

    assert [(f.category, f.change, f.path, f.new) for f in result.findings] == [
        (
            Category.FIELD,
            ChangeKind.ADDED,
            "details/table_product_sales/fields/Sales[Region]",
            "Values",
        ),
        (
            Category.PARSE_ISSUE,
            ChangeKind.ERROR,
            "new/Sales.Report/definition/pages/overview/visuals/card_total_sales"
            "/visual.json",
            None,
        ),
    ]
    assert result.findings[1].visual_path == "overview/card_total_sales"
