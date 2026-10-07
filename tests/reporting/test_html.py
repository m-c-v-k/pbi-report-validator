import re
import shutil
from pathlib import Path

import pytest

from pbi_report_validator.domain.models import (
    SCHEMA_VERSION,
    Category,
    ChangeKind,
    DiffResult,
    Finding,
    ItemStatus,
    PageView,
    Position,
    VisualView,
)
from pbi_report_validator.integrations.templates import (
    TemplateNotFoundError,
    read_template,
)
from pbi_report_validator.reporting.html import (
    REPORT_TEMPLATE,
    to_html,
    visual_key,
)
from pbi_report_validator.reporting.labels import CATEGORY_LABELS
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES

TEMPLATE = read_template(REPORT_TEMPLATE)


def render(result: DiffResult) -> str:
    return to_html(result, TEMPLATE, "9.9.9")


def fixture_html() -> str:
    return render(validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2"))


def test_fixture_report_shows_counts_and_every_finding() -> None:
    html = fixture_html()

    assert '<div class="n" data-count="total">7</div>' in html
    assert '<div class="n" data-count="measure">2</div>' in html
    assert html.count('<tr data-category="') == 7
    assert "Page &#39;Trends&#39; added with 1 visual" in html
    footer = f"pbi-report-validator</a>\n  9.9.9 &middot; schema {SCHEMA_VERSION}"
    assert footer in html


def test_output_is_deterministic() -> None:
    assert fixture_html() == fixture_html()


def test_page_is_self_contained() -> None:
    html = fixture_html()

    assert not re.search(r"<(script|img|iframe)[^>]+src=", html)
    assert not re.search(r"<link[^>]+href=", html)
    assert "@import" not in html


def test_values_and_names_are_escaped() -> None:
    finding = Finding(
        category=Category.VISUAL,
        change=ChangeKind.ADDED,
        path="p/<b>",
        message="<script>alert(1)</script>",
        new="a & b",
    )

    html = render(DiffResult(old_source="o", new_source="n", findings=(finding,)))

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "p/&lt;b&gt;" in html
    assert "a &amp; b" in html


def test_no_findings_shows_message_and_no_table() -> None:
    html = render(DiffResult(old_source="o", new_source="n"))

    assert "No differences found." in html
    assert 'id="findings"' not in html


def test_missing_template_raises() -> None:
    with pytest.raises(TemplateNotFoundError):
        read_template("does-not-exist.j2")


def test_every_category_has_a_label() -> None:
    assert set(CATEGORY_LABELS) == set(Category)


def test_every_change_kind_has_a_colour_rule() -> None:
    for change in ChangeKind:
        assert f".change-{change.value}" in TEMPLATE


def page_svg(html: str, page: str) -> str:
    start = html.index(f'id="page-{page}"')
    return html[start : html.index("</figure>", start)]


def test_each_page_has_a_wireframe_with_every_visual() -> None:
    html = fixture_html()

    assert html.count('<figure class="page"') == 3
    overview = page_svg(html, "overview")
    assert 'viewBox="0 0 1280.0 720.0"' in overview
    new_layer = overview[
        overview.index('class="layout-new"') : overview.index('class="layout-old"')
    ]
    assert new_layer.count('<g class="visual') == 4


def test_status_classes_and_marks_in_wireframes() -> None:
    html = fixture_html()

    overview = page_svg(html, "overview")
    assert (
        'class="visual status-modified" data-visual="chart_sales_by_month"' in overview
    )
    assert 'class="visual status-unchanged" data-visual="card_total_sales"' in overview
    trends = page_svg(html, "trends")
    assert 'class="visual status-added" data-visual="chart_margin_by_month"' in trends
    assert ">+ Margin by month</text>" in trends


def test_moved_visual_shows_previous_position() -> None:
    details = page_svg(fixture_html(), "details")

    assert (
        '<rect class="previous" x="840.0" y="40.0" width="400.0" height="320.0"'
        in details
    )
    assert 'data-visual="chart_sales_by_region"' in details
    assert 'x="840.0" y="360.0" width="400.0" height="320.0"' in details


def test_layout_toggle_only_on_modified_pages() -> None:
    html = fixture_html()

    assert 'class="layout-toggle"' in page_svg(html, "overview")
    assert 'class="layout-toggle"' not in page_svg(html, "trends")


def test_visual_missing_in_one_version_is_a_ghost_in_that_layout() -> None:
    result = DiffResult(
        old_source="o",
        new_source="n",
        pages=(
            PageView(
                name="p",
                display_name="P",
                status=ItemStatus.MODIFIED,
                ordinal=0,
                width=100,
                height=100,
                visuals=(
                    VisualView(
                        name="gone",
                        visual_type="card",
                        status=ItemStatus.REMOVED,
                        old_position=Position(x=1, y=2, width=3, height=4),
                    ),
                ),
            ),
        ),
    )

    svg = page_svg(render(result), "p")

    assert 'class="visual status-removed ghost" data-visual="gone"' in svg
    assert 'class="visual status-removed" data-visual="gone"' in svg


def single_visual_page(visual: VisualView) -> DiffResult:
    page = PageView(
        name="p",
        display_name="P",
        status=ItemStatus.MODIFIED,
        ordinal=0,
        width=100,
        height=100,
        visuals=(visual,),
    )
    return DiffResult(old_source="o", new_source="n", pages=(page,))


def test_added_visual_is_a_ghost_in_the_old_layout() -> None:
    added = VisualView(
        name="fresh",
        visual_type="card",
        status=ItemStatus.ADDED,
        new_position=Position(x=1, y=2, width=3, height=4),
    )

    svg = page_svg(render(single_visual_page(added)), "p")

    old_layer = svg[svg.index('class="layout-old"') :]
    assert 'class="visual status-added ghost" data-visual="fresh"' in old_layer


def test_visual_without_any_position_is_skipped_not_a_crash() -> None:
    nowhere = VisualView(name="lost", visual_type="card", status=ItemStatus.MODIFIED)

    svg = page_svg(render(single_visual_page(nowhere)), "p")

    assert 'data-visual="lost"' not in svg


def test_unchanged_label_has_no_leading_space() -> None:
    html = fixture_html()

    assert ">Total sales</text>" in html


def detail(html: str, key: str) -> str:
    start = html.index(f'<details class="visual-detail" id="{key}">')
    return html[start : html.index("</details>", start)]


def test_visuals_with_findings_get_a_detail_section() -> None:
    html = fixture_html()

    assert html.count('<details class="visual-detail"') == 4
    table = detail(html, "details/table_product_sales")
    assert "Filter visual_filter_category removed" in table
    assert "Product[Category] in (&#39;Bikes&#39;, &#39;Clothing&#39;)" in table
    moved = detail(html, "details/chart_sales_by_region")
    assert "x 840, y 40, 400 &times; 320 &rarr; x 840, y 360, 400 &times; 320" in moved


def test_wireframe_and_table_link_to_details() -> None:
    html = fixture_html()

    assert '<a href="#overview/slicer_year" data-open="overview/slicer_year">' in html
    key = "details/table_product_sales"
    link = (
        f'<a href="#{key}" data-open="{key}">{key}/filters/visual_filter_category</a>'
    )
    assert link in html
    assert 'href="#model/Sales/Total Sales"' not in html
    assert 'href="#trends"' not in html


def test_parse_issue_is_shown_on_its_visual(tmp_path: Path) -> None:
    new = tmp_path / "new"
    shutil.copytree(FIXTURES / "sales_v1", new)
    broken = (
        new / "Sales.Report/definition/pages/overview/visuals/card_margin/visual.json"
    )
    broken.write_text("{")

    html = render(validate(FIXTURES / "sales_v1", new))

    assert "Could not fully parse the new version" in detail(
        html, "overview/card_margin"
    )


@pytest.mark.parametrize(
    ("path", "visual", "expected"),
    [
        ("overview/slicer_year", None, "overview/slicer_year"),
        ("details/table_product_sales/filters/f", None, "details/table_product_sales"),
        (
            "new/Sales.Report/definition/pages/overview/visuals/card_margin/visual.json",
            "overview/card_margin",
            "overview/card_margin",
        ),
        ("overview/filters/page_filter", None, None),
        ("model/Sales/Total Sales", None, None),
        ("trends", None, None),
    ],
)
def test_visual_key(path: str, visual: str | None, expected: str | None) -> None:
    keys = {
        "overview/slicer_year",
        "details/table_product_sales",
        "overview/card_margin",
    }
    finding = Finding(
        category=Category.PARSE_ISSUE if visual else Category.VISUAL,
        change=ChangeKind.ERROR,
        path=path,
        message="m",
        visual=visual,
    )

    assert visual_key(finding, keys) == expected
