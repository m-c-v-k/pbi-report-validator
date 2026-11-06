import json
from typing import Any

import pytest

from pbi_report_validator.domain.models import (
    FieldKind,
    FieldRef,
    Page,
    Position,
    Report,
    SourceLocation,
)
from pbi_report_validator.domain.raw import RawJsonFile, RawLegacyReport, RawReport
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.legacy import decode, parse_legacy_report
from pbi_report_validator.parsers.pbir import parse_report
from tests.factories import FIXTURES

FILE = "Sales.Report/report.json"
TOTAL_SALES = FieldRef(table="Sales", name="Total Sales", kind=FieldKind.MEASURE)


def legacy(*sections: Any) -> Report:
    raw = RawJsonFile(path=FILE, content={"sections": list(sections)})
    return parse_legacy_report(RawLegacyReport(path="Sales.Report", layout=raw))


def section(name: str, *containers: Any, ordinal: int | None = None) -> dict[str, Any]:
    content: dict[str, Any] = {
        "name": name,
        "displayName": name.title(),
        "width": 1280,
        "height": 720,
        "visualContainers": list(containers),
    }
    if ordinal is not None:
        content["ordinal"] = ordinal
    return content


def container(config: dict[str, Any] | str, **position: float) -> dict[str, Any]:
    encoded = config if isinstance(config, str) else json.dumps(config)
    return {"config": encoded, "filters": "[]", **position}


def card_config(name: str = "card") -> dict[str, Any]:
    return {
        "name": name,
        "layouts": [
            {"id": 0, "position": {"x": 1, "y": 2, "z": 3, "width": 4, "height": 5}}
        ],
        "singleVisual": {
            "visualType": "card",
            "projections": {"Values": [{"queryRef": "Sales.Total Sales"}]},
            "prototypeQuery": {
                "Version": 2,
                "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                "Select": [
                    {
                        "Measure": {
                            "Expression": {"SourceRef": {"Source": "s"}},
                            "Property": "Total Sales",
                        },
                        "Name": "Sales.Total Sales",
                        "NativeReferenceName": "Total Sales",
                    }
                ],
            },
            "vcObjects": {
                "title": [
                    {
                        "properties": {
                            "text": {"expr": {"Literal": {"Value": "'Sales'"}}}
                        }
                    }
                ]
            },
        },
    }


def legacy_fixture(name: str) -> RawLegacyReport:
    raw = load_project(FIXTURES / name).report
    assert isinstance(raw, RawLegacyReport)
    return raw


def without_sources(pages: tuple[Page, ...]) -> list[dict[str, Any]]:
    """Pages as plain data without locations, filters and slicer state.

    Filters and slicer selections are not read from the legacy format yet.
    """
    dumped = []
    for page in pages:
        data = page.model_dump(exclude={"location", "filters", "visuals"})
        unread = {
            "location": True,
            "filters": True,
            "slicer": True,
            "projections": {"__all__": {"location"}},
        }
        data["visuals"] = [v.model_dump(exclude=unread) for v in page.visuals]
        dumped.append(data)
    return dumped


@pytest.mark.parametrize("name", ["sales_v1", "sales_v2"])
def test_legacy_fixture_parses_like_pbir(name: str) -> None:
    pbir = load_project(FIXTURES / name).report
    assert isinstance(pbir, RawReport)

    expected = parse_report(pbir)
    actual = parse_legacy_report(legacy_fixture(f"{name}_legacy"))

    assert actual.issues == ()
    assert without_sources(actual.pages) == without_sources(expected.pages)


def test_locations_point_into_the_report_document() -> None:
    report = parse_legacy_report(legacy_fixture("sales_v1_legacy"))
    page = report.pages[0]
    visual = page.visuals[0]

    assert page.location == SourceLocation(file=FILE, pointer="/sections/0")
    assert visual.location == SourceLocation(
        file=FILE, pointer="/sections/0/visualContainers/0"
    )
    assert visual.projections[0].location == SourceLocation(
        file=FILE, pointer="/sections/0/visualContainers/0/config"
    )


def test_visual_with_title_position_and_field() -> None:
    report = legacy(section("overview", container(card_config())))

    visual = report.pages[0].visuals[0]
    assert visual.name == "card"
    assert visual.visual_type == "card"
    assert visual.title == "Sales"
    assert visual.position == Position(x=1, y=2, z=3, width=4, height=5)
    assert [(p.role, p.field) for p in visual.projections] == [("Values", TOTAL_SALES)]


def test_pages_follow_section_ordinal() -> None:
    report = legacy(section("b", ordinal=1), section("a", ordinal=0), section("c"))

    assert [(p.name, p.ordinal) for p in report.pages] == [("a", 0), ("b", 1), ("c", 2)]


def test_position_falls_back_to_the_container() -> None:
    config = card_config()
    del config["layouts"]

    report = legacy(
        section("p", container(config, x=10, y=20, z=0, width=30, height=40))
    )

    assert report.pages[0].visuals[0].position == Position(
        x=10, y=20, z=0, width=30, height=40
    )


def test_visual_group_has_group_type() -> None:
    config = {
        "name": "group",
        "layouts": [{"position": {"x": 0, "y": 0, "width": 10, "height": 10}}],
        "singleVisualGroup": {"displayName": "Group"},
    }

    report = legacy(section("p", container(config)))

    assert report.pages[0].visuals[0].visual_type == "group"


def test_unreadable_config_becomes_an_issue() -> None:
    report = legacy(section("p", container("{not json"), container(card_config())))

    assert [v.name for v in report.pages[0].visuals] == ["card"]
    (issue,) = report.issues
    assert issue.path == FILE
    assert issue.visual_path == "p/visualContainers[0]"
    assert issue.message.startswith("visual config is unreadable")


def test_visual_without_position_becomes_an_issue() -> None:
    config = card_config()
    config["layouts"] = [{"position": {"x": 0}}]

    report = legacy(section("p", container(config)))

    assert report.pages[0].visuals == ()
    (issue,) = report.issues
    assert issue.visual_path == "p/card"
    assert "missing y, width, height" in issue.message


def test_field_missing_from_query_is_skipped_with_a_message() -> None:
    config = card_config()
    config["singleVisual"]["projections"]["Values"].append({"queryRef": "Sales.Other"})

    report = legacy(section("p", container(config)))

    assert len(report.pages[0].visuals[0].projections) == 1
    (issue,) = report.issues
    assert issue.visual_path == "p/card"
    assert "'Sales.Other'" in issue.message


def test_section_without_name_is_skipped() -> None:
    report = legacy({"displayName": "No name"}, section("ok"))

    assert [p.name for p in report.pages] == ["ok"]
    assert report.pages[0].ordinal == 1
    assert report.issues[0].message == "section 0 has no name; page skipped"


def test_sections_not_a_list() -> None:
    raw = RawJsonFile(path=FILE, content={"sections": {}})

    report = parse_legacy_report(RawLegacyReport(path="Sales.Report", layout=raw))

    assert report.pages == ()
    assert report.issues[0].message == "sections is not a list; no pages were read"


@pytest.mark.parametrize(
    ("value", "reason"),
    [(None, "not a JSON string"), ("[]", "not a JSON object"), ("{", "Expecting")],
)
def test_decode_failures(value: Any, reason: str) -> None:
    decoded, error = decode(value)

    assert decoded is None
    assert error is not None
    assert error.startswith(reason)
