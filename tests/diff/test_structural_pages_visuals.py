from pbi_report_validator.diff.structural import (
    diff_pages_and_visuals,
    without_unparseable,
)
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Page,
    ParseIssue,
    Visual,
)
from pbi_report_validator.matching.matcher import match_reports
from tests import factories
from tests.factories import fixture_pages


def visual(
    name: str,
    visual_type: str = "card",
    title: str | None = "T",
    x: float = 0,
    y: float = 0,
    width: float = 100,
    z: int = 0,
) -> Visual:
    return factories.visual(name, visual_type, title=title, x=x, y=y, width=width, z=z)


def page(name: str, ordinal: int, *visuals: Visual, display: str | None = None) -> Page:
    return factories.page(name, *visuals, ordinal=ordinal, display=display)


def diff(old: list[Page], new: list[Page]) -> list[tuple[str, Category, ChangeKind]]:
    findings = diff_pages_and_visuals(match_reports(old, new))
    return sorted((f.path, f.category, f.change) for f in findings)


def test_fixture_pages_and_visuals_changes() -> None:
    findings = diff_pages_and_visuals(
        match_reports(fixture_pages("sales_v1"), fixture_pages("sales_v2"))
    )

    summary = sorted((f.path, f.category, f.change, f.old, f.new) for f in findings)
    assert summary == [
        (
            "details/chart_sales_by_region",
            Category.VISUAL,
            ChangeKind.MOVED,
            "x=840, y=40, width=400, height=320",
            "x=840, y=360, width=400, height=320",
        ),
        (
            "overview/chart_sales_by_month",
            Category.VISUAL,
            ChangeKind.RETYPED,
            "clusteredColumnChart",
            "lineChart",
        ),
        ("trends", Category.PAGE, ChangeKind.ADDED, None, "Trends"),
    ]
    added = next(f for f in findings if f.change == ChangeKind.ADDED)
    assert added.message == "Page 'Trends' added with 1 visual"


def test_identical_reports_have_no_findings() -> None:
    pages = fixture_pages("sales_v1")

    assert diff_pages_and_visuals(match_reports(pages, pages)) == []


def test_removed_page() -> None:
    assert diff([page("a", 0), page("b", 1)], [page("a", 0)]) == [
        ("b", Category.PAGE, ChangeKind.REMOVED)
    ]


def test_renamed_page() -> None:
    findings = diff_pages_and_visuals(
        match_reports([page("a", 0, display="Old")], [page("a", 0, display="New")])
    )

    assert [(f.change, f.old, f.new) for f in findings] == [
        (ChangeKind.RENAMED, "Old", "New")
    ]


def test_reordered_pages_ignore_added_pages() -> None:
    old = [page("a", 0), page("b", 1), page("c", 2)]
    new = [page("new", 0), page("a", 1), page("c", 2), page("b", 3)]

    assert diff(old, new) == [
        ("b", Category.PAGE, ChangeKind.REORDERED),
        ("c", Category.PAGE, ChangeKind.REORDERED),
        ("new", Category.PAGE, ChangeKind.ADDED),
    ]


def test_added_and_removed_visuals() -> None:
    old = [page("p", 0, visual("keep"), visual("gone", "map", x=900, y=900))]
    new = [page("p", 0, visual("keep"), visual("fresh", "table", "Other", x=0, y=900))]

    assert diff(old, new) == [
        ("p/fresh", Category.VISUAL, ChangeKind.ADDED),
        ("p/gone", Category.VISUAL, ChangeKind.REMOVED),
    ]


def test_title_change_and_resize() -> None:
    old = [page("p", 0, visual("v", title="Sales"))]
    new = [page("p", 0, visual("v", title="Revenue", width=200))]

    findings = diff_pages_and_visuals(match_reports(old, new))

    assert sorted((f.change, f.old, f.new) for f in findings) == [
        (
            ChangeKind.MODIFIED,
            "Sales",
            "Revenue",
        ),
        (
            ChangeKind.MOVED,
            "x=0, y=0, width=100, height=100",
            "x=0, y=0, width=200, height=100",
        ),
    ]
    moved = next(f for f in findings if f.change == ChangeKind.MOVED)
    assert moved.message == "card 'Revenue' (v) resized"


def test_new_visual_id_is_reported_as_renamed() -> None:
    old = [page("p", 0, visual("old_id"))]
    new = [page("p", 0, visual("new_id"))]

    findings = diff_pages_and_visuals(match_reports(old, new))

    assert [(f.path, f.change, f.old, f.new) for f in findings] == [
        ("p/old_id", ChangeKind.RENAMED, "old_id", "new_id")
    ]


def test_new_page_id_is_reported_as_renamed() -> None:
    old = [page("a1", 0, visual("v"), display="Sales")]
    new = [page("b2", 0, visual("v"), display="Sales")]

    findings = diff_pages_and_visuals(match_reports(old, new))

    assert [(f.path, f.change, f.old, f.new) for f in findings] == [
        ("a1", ChangeKind.RENAMED, "a1", "b2")
    ]


def test_removed_page_message_counts_visuals() -> None:
    old = [page("a", 0), page("b", 1, visual("x"), visual("y"))]

    findings = diff_pages_and_visuals(match_reports(old, [page("a", 0)]))

    assert findings[0].message == "Page 'B' removed with 2 visuals"


def test_z_order_change_alone_is_ignored() -> None:
    old = [page("p", 0, visual("v"))]
    new = [page("p", 0, visual("v", z=5000))]

    assert diff_pages_and_visuals(match_reports(old, new)) == []


def test_title_added_and_removed() -> None:
    old = [page("p", 0, visual("a", title=None), visual("b", title="B", x=500))]
    new = [page("p", 0, visual("a", title="A"), visual("b", title=None, x=500))]

    findings = diff_pages_and_visuals(match_reports(old, new))

    assert sorted((f.path, f.old, f.new) for f in findings) == [
        ("p/a", None, "A"),
        ("p/b", "B", None),
    ]


def test_new_id_and_retype_are_both_reported() -> None:
    old = [page("p", 0, visual("old_id", "clusteredBarChart", "Sales"))]
    new = [page("p", 0, visual("new_id", "clusteredColumnChart", "Sales"))]

    findings = diff_pages_and_visuals(match_reports(old, new, threshold=0.5))

    assert sorted((f.path, f.change) for f in findings) == [
        ("p/old_id", ChangeKind.RENAMED),
        ("p/old_id", ChangeKind.RETYPED),
    ]


def test_unparseable_visuals_are_not_reported_added_or_removed() -> None:
    findings = diff_pages_and_visuals(
        match_reports(
            [page("p", 0, visual("a"), visual("b", x=500))], [page("p", 0, visual("a"))]
        )
    )
    issue = ParseIssue(
        path="pages/p/visuals/b/visual.json", message="boom", visual="p/b"
    )

    assert without_unparseable(findings, [], [issue]) == []
    assert without_unparseable(findings, [issue], []) == findings


def test_unparseable_pages_are_not_reported_added_or_removed() -> None:
    findings = diff_pages_and_visuals(
        match_reports([page("a", 0), page("b", 1)], [page("a", 0)])
    )
    issue = ParseIssue(path="pages/b/page.json", message="boom", page="b")

    assert without_unparseable(findings, [], [issue]) == []
    assert without_unparseable(findings, [issue], []) == findings
