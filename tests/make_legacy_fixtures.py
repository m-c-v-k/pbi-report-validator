"""Build the legacy-format fixtures from the PBIR sales fixtures.

``sales_v1_legacy`` and ``sales_v2_legacy`` are copies of ``sales_v1`` and
``sales_v2`` with the report saved in the legacy format: one
``Sales.Report/report.json`` whose config and filters are JSON-encoded
strings, as Power BI Desktop writes it without PBIR (and as ``Report/Layout``
inside ``.pbit`` and ``.pbix``). The semantic model is copied unchanged.

``tests/test_fixtures.py`` checks that the committed fixtures match this
script. After changing a PBIR fixture, run it again::

    uv run python -m tests.make_legacy_fixtures
"""

import json
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"
SOURCES = ("sales_v1", "sales_v2")
LEGACY_SUFFIX = "_legacy"
REPORT_FOLDER = "Sales.Report"
# Layout version of the legacy config, as written by recent Desktop versions.
LAYOUT_VERSION = "5.61"
DISPLAY_OPTIONS = {"FitToPage": 1, "FitToWidth": 2, "ActualSize": 3}
SHARED_RESOURCES = 2
BASE_THEME = 202

JsonObject = dict[str, Any]


def build_all() -> None:
    for name in SOURCES:
        build(FIXTURES / name, FIXTURES / f"{name}{LEGACY_SUFFIX}")


def build(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=_skip_pbir_definition)
    definition = source / REPORT_FOLDER / "definition"
    text = json.dumps(legacy_report(definition), indent=2, ensure_ascii=False)
    (target / REPORT_FOLDER / "report.json").write_text(
        text + "\n", encoding="utf-8", newline="\n"
    )


def _skip_pbir_definition(directory: str, names: Iterable[str]) -> set[str]:
    return {"definition"} if directory.endswith(".Report") else set()


def legacy_report(definition: Path) -> JsonObject:
    report = _load(definition / "report.json")
    pages = _load(definition / "pages" / "pages.json")
    order: list[str] = pages["pageOrder"]
    theme = report["themeCollection"]["baseTheme"]["name"]
    return {
        "config": _encode(_report_config(report, order, pages["activePageName"])),
        "filters": _encode(legacy_filters(report)),
        "layoutOptimization": 0,
        "resourcePackages": [_theme_package(theme)],
        "sections": [
            legacy_section(definition / "pages" / name, ordinal)
            for ordinal, name in enumerate(order)
        ],
    }


def _report_config(report: JsonObject, order: list[str], active: str) -> JsonObject:
    theme = report["themeCollection"]["baseTheme"]["name"]
    return {
        "version": LAYOUT_VERSION,
        "themeCollection": {
            "baseTheme": {
                "name": theme,
                "version": LAYOUT_VERSION,
                "type": SHARED_RESOURCES,
            }
        },
        "activeSectionIndex": order.index(active),
        "settings": report.get("settings", {}),
    }


def _theme_package(theme: str) -> JsonObject:
    return {
        "resourcePackage": {
            "name": "SharedResources",
            "type": SHARED_RESOURCES,
            "items": [
                {"type": BASE_THEME, "path": f"BaseThemes/{theme}.json", "name": theme}
            ],
            "disabled": False,
        }
    }


def legacy_filters(container: JsonObject) -> list[JsonObject]:
    filters = container.get("filterConfig", {}).get("filters", [])
    return [_legacy_filter(f) for f in filters]


def _legacy_filter(pbir: JsonObject) -> JsonObject:
    legacy: JsonObject = {"name": pbir["name"], "expression": pbir["field"]}
    legacy.update((k, v) for k, v in pbir.items() if k not in {"name", "field"})
    legacy.setdefault("howCreated", 1)
    return legacy


def legacy_section(page_dir: Path, ordinal: int) -> JsonObject:
    page = _load(page_dir / "page.json")
    visuals = sorted(p for p in (page_dir / "visuals").iterdir() if p.is_dir())
    return {
        "name": page["name"],
        "displayName": page["displayName"],
        "displayOption": DISPLAY_OPTIONS[page["displayOption"]],
        "filters": _encode(legacy_filters(page)),
        "height": page["height"],
        "width": page["width"],
        "ordinal": ordinal,
        "config": _encode({}),
        "visualContainers": [
            legacy_container(_load(v / "visual.json")) for v in visuals
        ],
    }


def legacy_container(container: JsonObject) -> JsonObject:
    position = container["position"]
    config = {
        "name": container["name"],
        "layouts": [{"id": 0, "position": position}],
        "singleVisual": _single_visual(container["visual"]),
    }
    return {
        "x": position["x"],
        "y": position["y"],
        "z": position["z"],
        "width": position["width"],
        "height": position["height"],
        "config": _encode(config),
        "filters": _encode(legacy_filters(container)),
    }


def _single_visual(visual: JsonObject) -> JsonObject:
    roles: JsonObject = visual.get("query", {}).get("queryState", {})
    single: JsonObject = {
        "visualType": visual["visualType"],
        "projections": {
            role: [{"queryRef": p["queryRef"]} for p in spec["projections"]]
            for role, spec in roles.items()
        },
        "prototypeQuery": _prototype_query(roles),
        "drillFilterOtherVisuals": True,
    }
    if "objects" in visual:
        single["objects"] = visual["objects"]
    if "visualContainerObjects" in visual:
        single["vcObjects"] = visual["visualContainerObjects"]
    return single


def _prototype_query(roles: JsonObject) -> JsonObject:
    aliases: dict[str, str] = {}
    select: list[JsonObject] = []
    seen: set[str] = set()
    for spec in roles.values():
        for projection in spec["projections"]:
            if projection["queryRef"] in seen:
                continue
            seen.add(projection["queryRef"])
            select.append(_select_item(projection, aliases))
    return {
        "Version": 2,
        "From": [
            {"Name": alias, "Entity": entity, "Type": 0}
            for entity, alias in aliases.items()
        ],
        "Select": select,
    }


def _select_item(projection: JsonObject, aliases: dict[str, str]) -> JsonObject:
    ((kind, body),) = projection["field"].items()
    if kind not in {"Column", "Measure"}:
        raise ValueError(f"Unsupported field kind in fixture: {kind}")
    entity = body["Expression"]["SourceRef"]["Entity"]
    return {
        kind: {
            "Expression": {"SourceRef": {"Source": _alias(entity, aliases)}},
            "Property": body["Property"],
        },
        "Name": projection["queryRef"],
        "NativeReferenceName": projection["nativeQueryRef"],
    }


def _alias(entity: str, aliases: dict[str, str]) -> str:
    if entity not in aliases:
        base = entity[0].lower()
        taken = set(aliases.values())
        alias, n = base, 1
        while alias in taken:
            alias, n = f"{base}{n}", n + 1
        aliases[entity] = alias
    return aliases[entity]


def _encode(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    build_all()
