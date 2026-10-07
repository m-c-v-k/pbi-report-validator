import json
from pathlib import Path

import pytest

from tests.factories import FIXTURES

JSON_SUFFIXES = {".json", ".pbip", ".pbir", ".pbism"}
JSON_FILES = sorted(
    p for p in FIXTURES.rglob("*") if p.is_file() and p.suffix in JSON_SUFFIXES
)


def test_fixtures_contain_json_files() -> None:
    assert JSON_FILES


@pytest.mark.parametrize(
    "path", JSON_FILES, ids=lambda p: p.relative_to(FIXTURES).as_posix()
)
def test_fixture_json_is_valid(path: Path) -> None:
    json.loads(path.read_text(encoding="utf-8"))
