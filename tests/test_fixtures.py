import json
from pathlib import Path
from typing import Any

import pytest

from pbi_report_validator.domain.models import Category, ChangeKind
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES
from tests.make_legacy_fixtures import LEGACY_SUFFIX, SOURCES, build
from tests.pbit import write_pbit

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


@pytest.mark.parametrize("version", ["sales_v1", "sales_v2", "sales_v3"])
def test_fixture_base_theme_version_is_an_object(version: str) -> None:
    # report/3.0.0 needs an object here; Power BI Desktop refuses a string.
    report = FIXTURES / version / "Sales.Report/definition/report.json"
    theme = json.loads(report.read_text(encoding="utf-8"))["themeCollection"]
    assert set(theme["baseTheme"]["reportVersionAtImport"]) == {
        "visual",
        "report",
        "page",
    }


@pytest.mark.parametrize("source", SOURCES)
def test_legacy_fixture_matches_generator(source: str, tmp_path: Path) -> None:
    committed = FIXTURES / f"{source}{LEGACY_SUFFIX}"
    generated = tmp_path / committed.name
    build(FIXTURES / source, generated)

    assert _tree(committed) == _tree(generated)


@pytest.mark.parametrize("source", SOURCES)
def test_legacy_fixture_has_the_pbir_pages_and_visuals(source: str) -> None:
    report = _legacy_report(FIXTURES / f"{source}{LEGACY_SUFFIX}")
    pages = FIXTURES / source / "Sales.Report/definition/pages"
    order = json.loads((pages / "pages.json").read_text(encoding="utf-8"))

    assert [s["name"] for s in report["sections"]] == order["pageOrder"]
    for section in report["sections"]:
        visuals = sorted(
            p.name for p in (pages / section["name"] / "visuals").iterdir()
        )
        names = [json.loads(v["config"])["name"] for v in section["visualContainers"]]
        assert names == visuals


@pytest.mark.parametrize("source", SOURCES)
def test_legacy_fixture_strings_are_json(source: str) -> None:
    report = _legacy_report(FIXTURES / f"{source}{LEGACY_SUFFIX}")
    containers = [v for s in report["sections"] for v in s["visualContainers"]]
    encoded = [report["config"], report["filters"]]
    encoded += [s[k] for s in report["sections"] for k in ("config", "filters")]
    encoded += [v[k] for v in containers for k in ("config", "filters")]

    for text in encoded:
        assert isinstance(text, str)
        json.loads(text)


def test_legacy_fixture_has_no_pbir_definition() -> None:
    for source in SOURCES:
        report_folder = FIXTURES / f"{source}{LEGACY_SUFFIX}" / "Sales.Report"
        assert not (report_folder / "definition").exists()
        assert (report_folder / "report.json").is_file()


def _legacy_report(project: Path) -> dict[str, Any]:
    text = (project / "Sales.Report/report.json").read_text(encoding="utf-8")
    report: dict[str, Any] = json.loads(text)
    return report


def _tree(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_legacy_pair_reports_the_pbir_findings() -> None:
    def findings(old: str, new: str) -> list[tuple[str, str, str, str | None]]:
        result = validate(FIXTURES / old, FIXTURES / new)
        return [(f.category, f.change, f.path, f.new) for f in result.findings]

    expected = findings("sales_v1", "sales_v2")
    assert findings("sales_v1_legacy", "sales_v2_legacy") == expected
    assert {c for c, *_ in expected} >= {Category.FILTER, Category.SLICER}


def test_pbit_pair_reports_the_pbip_findings(tmp_path: Path) -> None:
    old = write_pbit(FIXTURES / "sales_v1_legacy", tmp_path / "v1.pbit")
    new = write_pbit(FIXTURES / "sales_v2_legacy", tmp_path / "v2.pbit")

    expected = _findings(FIXTURES / "sales_v1", FIXTURES / "sales_v2")

    assert _findings(old, new) == expected
    assert {c for c, *_ in expected} >= {Category.MEASURE, Category.FILTER}


def test_pbit_compares_with_pbip_both_ways(tmp_path: Path) -> None:
    old = write_pbit(FIXTURES / "sales_v1_legacy", tmp_path / "v1.pbit")
    new = write_pbit(FIXTURES / "sales_v2_legacy", tmp_path / "v2.pbit")

    expected = _findings(FIXTURES / "sales_v1", FIXTURES / "sales_v2")

    assert _findings(old, FIXTURES / "sales_v2") == expected
    assert _findings(FIXTURES / "sales_v1", new) == expected


def _findings(old: Path, new: Path) -> list[tuple[str, str, str, str | None]]:
    result = validate(old, new)
    return [(f.category, f.change, f.path, f.new) for f in result.findings]
