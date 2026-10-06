from pathlib import Path

import pytest

from pbi_report_validator.domain.models import (
    FieldKind,
    FieldRef,
    MatchMethod,
    Page,
    Position,
    Projection,
    Visual,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.matching.matcher import (
    match_reports,
    match_visuals,
    similarity,
)
from pbi_report_validator.parsers.pbir import parse_report

FIXTURES = Path(__file__).parent.parent / "fixtures"


def fixture_pages(name: str) -> tuple[Page, ...]:
    return parse_report(load_project(FIXTURES / name).report).pages


def visual(
    name: str,
    visual_type: str = "card",
    title: str | None = None,
    fields: tuple[str, ...] = ("Total Sales",),
    x: float = 0,
    y: float = 0,
) -> Visual:
    return Visual(
        name=name,
        visual_type=visual_type,
        title=title,
        position=Position(x=x, y=y, width=100, height=100),
        projections=tuple(
            Projection(
                role="Values",
                field=FieldRef(table="Sales", name=f, kind=FieldKind.MEASURE),
            )
            for f in fields
        ),
    )


def page(
    name: str, *visuals: Visual, display: str | None = None, ordinal: int = 0
) -> Page:
    return Page(
        name=name,
        display_name=display or name.title(),
        ordinal=ordinal,
        width=1000,
        height=1000,
        visuals=visuals,
    )


def test_fixture_pages_and_visuals_match_by_id() -> None:
    result = match_reports(fixture_pages("sales_v1"), fixture_pages("sales_v2"))

    assert [(m.old.name, m.method) for m in result.pages] == [
        ("overview", MatchMethod.ID),
        ("details", MatchMethod.ID),
    ]
    assert [p.name for p in result.added_pages] == ["trends"]
    assert result.removed_pages == ()
    for page_match in result.pages:
        assert page_match.removed_visuals == ()
        assert page_match.added_visuals == ()
        assert all(v.method == MatchMethod.ID for v in page_match.visuals)
    overview = {v.old.name: v for v in result.pages[0].visuals}
    retyped = overview["chart_sales_by_month"]
    assert (retyped.old.visual_type, retyped.new.visual_type) == (
        "clusteredColumnChart",
        "lineChart",
    )
    details = {v.old.name: v for v in result.pages[1].visuals}
    moved = details["chart_sales_by_region"]
    assert (moved.old.position.y, moved.new.position.y) == (40, 360)


def test_pages_fall_back_to_display_name() -> None:
    old = [page("a1", display="Sales")]
    new = [page("b7", display="Sales")]

    result = match_reports(old, new)

    assert [(m.old.name, m.new.name, m.method) for m in result.pages] == [
        ("a1", "b7", MatchMethod.DISPLAY_NAME)
    ]


def test_duplicate_display_names_are_not_matched() -> None:
    old = [page("a", display="Same"), page("b", display="Same", ordinal=1)]
    new = [page("c", display="Same")]

    result = match_reports(old, new)

    assert result.pages == ()
    assert [p.name for p in result.removed_pages] == ["a", "b"]
    assert [p.name for p in result.added_pages] == ["c"]


def test_renamed_visual_is_matched_by_similarity() -> None:
    old = page(
        "p", visual("v_old", title="Sales"), visual("other", "table", x=800, y=800)
    )
    new = page(
        "p", visual("v_new", title="Sales"), visual("other", "table", x=800, y=800)
    )

    matches, removed, added = match_visuals(old, new)

    assert [(m.old.name, m.new.name, m.method) for m in matches] == [
        ("other", "other", MatchMethod.ID),
        ("v_old", "v_new", MatchMethod.SIMILARITY),
    ]
    assert matches[1].score == 1.0
    assert (removed, added) == ([], [])


def test_dissimilar_visuals_stay_unmatched() -> None:
    old = page("p", visual("a", "card", "Revenue", ("Total Sales",), x=0, y=0))
    new = page("p", visual("b", "map", "Stores", ("Store Count",), x=900, y=900))

    matches, removed, added = match_visuals(old, new)

    assert matches == []
    assert [v.name for v in removed] == ["a"]
    assert [v.name for v in added] == ["b"]


def test_best_scoring_candidate_wins_and_ties_are_deterministic() -> None:
    old = page("p", visual("a", x=0), visual("b", x=0))
    new = page("p", visual("x", x=0), visual("y", x=0))

    first = match_visuals(old, new)
    second = match_visuals(old, new)

    assert [(m.old.name, m.new.name) for m in first[0]] == [("a", "x"), ("b", "y")]
    assert first == second


def test_threshold_controls_similarity_matches() -> None:
    old = page("p", visual("a", title="One"))
    new = page("p", visual("b", title="Two"))

    assert match_visuals(old, new, threshold=0.9)[0] == []
    assert len(match_visuals(old, new, threshold=0.5)[0]) == 1


BASE = visual("a", title="T")


@pytest.mark.parametrize(
    ("other", "expected"),
    [
        (visual("b", title="T"), 1.0),
        (visual("b", "table", title="T"), 0.7),
        (visual("b", title="Other"), 0.8),
        (visual("b", title="T", fields=("Other",)), 0.7),
    ],
)
def test_similarity_weights(other: Visual, expected: float) -> None:
    p = page("p")

    assert similarity(BASE, other, p, p) == pytest.approx(expected)


def test_position_closeness_is_relative_to_page_size() -> None:
    small = page("p")
    large = Page(name="p", display_name="P", ordinal=0, width=2000, height=2000)
    moved = visual("b", title="T", x=500)
    scaled = Visual(
        name="b",
        visual_type="card",
        title="T",
        position=Position(x=0, y=0, width=200, height=200),
        projections=BASE.projections,
    )

    assert 0.8 < similarity(BASE, moved, small, small) < 1.0
    assert similarity(BASE, scaled, small, large) == pytest.approx(1.0)


def test_untitled_visuals_without_fields_agree_on_title_and_fields() -> None:
    a = visual("a", "card", None, (), x=0)
    b = visual("b", "table", None, (), x=900, y=900)
    p = page("p")

    assert similarity(a, b, p, p) == pytest.approx(0.5, abs=0.05)


def test_duplicate_visual_names_are_not_lost() -> None:
    old = page("p", visual("dup", title="A"), visual("dup", "map", "B", x=900, y=900))
    new = page("p", visual("fresh", title="A"))

    matches, removed, added = match_visuals(old, new)

    assert [(m.old.title, m.new.name) for m in matches] == [("A", "fresh")]
    assert [(v.name, v.title) for v in removed] == [("dup", "B")]
    assert added == []


@pytest.mark.parametrize("threshold", [-0.1, 1.5])
def test_threshold_outside_range_is_rejected(threshold: float) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        match_reports([], [], threshold=threshold)
