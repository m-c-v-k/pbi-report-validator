from pathlib import Path

from pbi_report_validator.domain.models import FieldKind, FieldRef, Position, Projection
from pbi_report_validator.domain.raw import RawJsonFile, RawPage, RawReport
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report, parse_visual

FIXTURES = Path(__file__).parent.parent / "fixtures"
TOTAL_SALES = FieldRef(table="Sales", name="Total Sales", kind=FieldKind.MEASURE)


def fixture_report(name: str) -> RawReport:
    return load_project(FIXTURES / name).report


def page_json(name: str) -> RawJsonFile:
    return RawJsonFile(
        path=f"pages/{name}/page.json",
        content={
            "name": name,
            "displayName": name.title(),
            "width": 1280,
            "height": 720,
        },
    )


def test_parses_sales_v1_pages_in_page_order() -> None:
    report = parse_report(fixture_report("sales_v1"))

    assert report.issues == ()
    assert [(p.name, p.display_name, p.ordinal) for p in report.pages] == [
        ("overview", "Overview", 0),
        ("details", "Details", 1),
    ]


def test_parses_sales_v1_visuals() -> None:
    overview = parse_report(fixture_report("sales_v1")).pages[0]

    visuals = {v.name: v for v in overview.visuals}
    assert sorted(visuals) == [
        "card_margin",
        "card_total_sales",
        "chart_sales_by_month",
        "slicer_year",
    ]
    card = visuals["card_total_sales"]
    assert card.visual_type == "card"
    assert card.title == "Total sales"
    assert card.position == Position(x=40, y=40, z=0, width=280, height=140)
    assert card.projections == (Projection(role="Values", field=TOTAL_SALES),)
    chart = visuals["chart_sales_by_month"]
    assert chart.visual_type == "clusteredColumnChart"
    assert [(p.role, p.field.key) for p in chart.projections] == [
        ("Category", "Date[Month]"),
        ("Y", "Sales[Total Sales]"),
    ]


def test_parses_sales_v2_changes() -> None:
    report = parse_report(fixture_report("sales_v2"))

    assert [p.name for p in report.pages] == ["overview", "details", "trends"]
    overview = {v.name: v for v in report.pages[0].visuals}
    assert overview["chart_sales_by_month"].visual_type == "lineChart"
    details = {v.name: v for v in report.pages[1].visuals}
    assert details["chart_sales_by_region"].position.y == 360


def test_unlisted_pages_follow_listed_ones() -> None:
    raw = RawReport(
        path="r",
        report=RawJsonFile(path="report.json"),
        pages_meta=RawJsonFile(path="pages.json", content={"pageOrder": ["b"]}),
        pages=(
            RawPage(name="c", page=page_json("c")),
            RawPage(name="a", page=page_json("a")),
            RawPage(name="b", page=page_json("b")),
        ),
    )

    assert [p.name for p in parse_report(raw).pages] == ["b", "a", "c"]


def test_broken_visual_becomes_issue_and_rest_is_parsed() -> None:
    good = RawJsonFile(
        path="pages/p/visuals/ok/visual.json",
        content={"name": "ok", "position": {"x": 0, "y": 0, "width": 1, "height": 1}},
    )
    broken = RawJsonFile(path="pages/p/visuals/bad/visual.json", error="boom")
    no_position = RawJsonFile(
        path="pages/p/visuals/np/visual.json", content={"name": "np"}
    )
    negative = RawJsonFile(
        path="pages/p/visuals/neg/visual.json",
        content={"name": "neg", "position": {"x": -5, "y": 0, "width": 1, "height": 1}},
    )
    raw = RawReport(
        path="r",
        report=RawJsonFile(path="report.json"),
        pages=(
            RawPage(
                name="p",
                page=page_json("p"),
                visuals=(good, broken, no_position, negative),
            ),
        ),
    )

    report = parse_report(raw)

    assert [v.name for v in report.pages[0].visuals] == ["ok"]
    assert [i.path for i in report.issues] == [
        broken.path,
        no_position.path,
        negative.path,
    ]
    assert "boom" in report.issues[0].message
    assert "position.x" in report.issues[2].message or "x" in report.issues[2].message


def test_broken_page_becomes_issue() -> None:
    raw = RawReport(
        path="r",
        report=RawJsonFile(path="report.json"),
        pages=(
            RawPage(
                name="bad", page=RawJsonFile(path="pages/bad/page.json", error="x")
            ),
            RawPage(name="ok", page=page_json("ok")),
        ),
    )

    report = parse_report(raw)

    assert [p.name for p in report.pages] == ["ok"]
    assert report.pages[0].ordinal == 1
    assert report.issues[0].path == "pages/bad/page.json"


def test_unknown_visual_type_is_kept() -> None:
    visual = parse_visual(
        {
            "name": "v",
            "position": {"x": 0, "y": 0, "width": 10, "height": 10},
            "visual": {"visualType": "myCustomVisual1234"},
        }
    )

    assert visual.visual_type == "myCustomVisual1234"
    assert visual.projections == ()


def test_visual_group_gets_group_type() -> None:
    visual = parse_visual(
        {
            "name": "g",
            "position": {"x": 0, "y": 0, "width": 10, "height": 10},
            "visualGroup": {"displayName": "Group"},
        }
    )

    assert visual.visual_type == "group"
