from pbi_report_validator.domain.models import FieldKind, FieldRef, Position, Projection
from pbi_report_validator.domain.raw import RawJsonFile, RawPage, RawReport
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report, parse_visual
from tests.factories import FIXTURES

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
    assert report.issues[1].message == "visual has no name or position"
    assert report.issues[2].message.startswith("invalid x:")


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
        },
        [],
    )

    assert visual.visual_type == "myCustomVisual1234"
    assert visual.projections == ()


def test_visual_group_gets_group_type() -> None:
    visual = parse_visual(
        {
            "name": "g",
            "position": {"x": 0, "y": 0, "width": 10, "height": 10},
            "visualGroup": {"displayName": "Group"},
        },
        [],
    )

    assert visual.visual_type == "group"


POSITION = {"x": 0, "y": 0, "width": 10, "height": 10}


def report_with_pages(*pages: RawPage, order: object = None) -> RawReport:
    meta = (
        None
        if order is None
        else RawJsonFile(path="pages.json", content={"pageOrder": order})
    )
    return RawReport(
        path="r", report=RawJsonFile(path="report.json"), pages_meta=meta, pages=pages
    )


def test_page_size_defaults_when_missing() -> None:
    page = RawPage(name="p", page=RawJsonFile(path="p/page.json", content={}))

    parsed = parse_report(report_with_pages(page)).pages[0]

    assert (parsed.name, parsed.display_name) == ("p", "p")
    assert (parsed.width, parsed.height) == (1280, 720)


def test_pages_sorted_by_name_without_pages_json() -> None:
    pages = (
        RawPage(name="b", page=page_json("b")),
        RawPage(name="a", page=page_json("a")),
    )

    assert [p.name for p in parse_report(report_with_pages(*pages)).pages] == ["a", "b"]


def test_non_string_page_order_entries_are_ignored() -> None:
    pages = (
        RawPage(name="a", page=page_json("a")),
        RawPage(name="b", page=page_json("b")),
    )

    report = parse_report(report_with_pages(*pages, order=[1, None, "b"]))

    assert [p.name for p in report.pages] == ["b", "a"]


def title_body(value: object) -> dict[str, object]:
    return {
        "visualType": "card",
        "visualContainerObjects": {
            "title": [{"properties": {"text": {"expr": {"Literal": {"Value": value}}}}}]
        },
    }


def test_title_unquotes_escaped_quotes() -> None:
    content = {
        "name": "v",
        "position": POSITION,
        "visual": title_body("'Bob''s sales'"),
    }

    assert parse_visual(content, []).title == "Bob's sales"


def test_malformed_title_gives_none() -> None:
    body = {"visualType": "card", "visualContainerObjects": {"title": "oops"}}

    visual = parse_visual({"name": "v", "position": POSITION, "visual": body}, [])

    assert visual.title is None


def test_unparseable_projections_are_reported() -> None:
    body = {
        "visualType": "table",
        "query": {
            "queryState": {
                "Values": {"projections": ["not a dict", {"field": {"Unknown": {}}}]},
                "Rows": "not a dict",
            }
        },
    }
    problems: list[str] = []

    visual = parse_visual({"name": "v", "position": POSITION, "visual": body}, problems)

    assert visual.projections == ()
    assert problems == ["unrecognised field in role Values was skipped"] * 2


def test_non_dict_query_state_gives_no_projections() -> None:
    body = {"visualType": "table", "query": {"queryState": []}}

    visual = parse_visual({"name": "v", "position": POSITION, "visual": body}, [])

    assert visual.projections == ()


def test_visual_without_body_is_unknown() -> None:
    assert (
        parse_visual({"name": "v", "position": POSITION}, []).visual_type == "unknown"
    )


def test_incomplete_position_is_an_issue() -> None:
    visual = RawJsonFile(
        path="p/visuals/v/visual.json",
        content={"name": "v", "position": {"x": 0, "y": 0}},
    )
    page = RawPage(name="p", page=page_json("p"), visuals=(visual,))

    report = parse_report(report_with_pages(page))

    assert report.pages[0].visuals == ()
    assert report.issues[0].message == "visual position is missing width, height"


def test_skipped_field_becomes_issue_but_visual_is_kept() -> None:
    body = {
        "visualType": "card",
        "query": {"queryState": {"Values": {"projections": [{"field": {}}]}}},
    }
    visual = RawJsonFile(
        path="p/visuals/v/visual.json",
        content={"name": "v", "position": POSITION, "visual": body},
    )
    page = RawPage(name="p", page=page_json("p"), visuals=(visual,))

    report = parse_report(report_with_pages(page))

    assert [v.name for v in report.pages[0].visuals] == ["v"]
    assert [i.path for i in report.issues] == ["p/visuals/v/visual.json"]


def test_visual_parse_issues_name_their_visual() -> None:
    broken = RawJsonFile(path="pages/p/visuals/bad_one/visual.json", error="boom")
    incomplete = RawJsonFile(
        path="pages/p/visuals/no_pos/visual.json", content={"name": "no_pos"}
    )
    page = RawPage(name="p", page=page_json("p"), visuals=(broken, incomplete))

    report = parse_report(report_with_pages(page))

    assert [(i.visual, i.path) for i in report.issues] == [
        ("p/bad_one", broken.path),
        ("p/no_pos", incomplete.path),
    ]


def test_page_level_issues_have_no_visual() -> None:
    page = RawPage(name="p", page=RawJsonFile(path="pages/p/page.json", error="x"))

    report = parse_report(report_with_pages(page))

    assert report.issues[0].visual is None


def test_unparseable_page_issues_name_their_page() -> None:
    unreadable = RawPage(
        name="bad", page=RawJsonFile(path="pages/bad/page.json", error="x")
    )
    invalid = RawPage(
        name="neg",
        page=RawJsonFile(
            path="pages/neg/page.json", content={"name": "neg", "width": -1}
        ),
    )

    report = parse_report(report_with_pages(unreadable, invalid))

    assert report.pages == ()
    assert [(i.page, i.path) for i in report.issues] == [
        ("bad", "pages/bad/page.json"),
        ("neg", "pages/neg/page.json"),
    ]
