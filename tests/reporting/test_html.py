import re
from pathlib import Path

import pytest

from pbi_report_validator.domain.models import Category, ChangeKind, DiffResult, Finding
from pbi_report_validator.integrations.templates import (
    TemplateNotFoundError,
    read_template,
)
from pbi_report_validator.reporting.html import (
    CATEGORY_LABELS,
    REPORT_TEMPLATE,
    to_html,
)
from pbi_report_validator.services.validate import validate

FIXTURES = Path(__file__).parent.parent / "fixtures"
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
    assert "pbi-report-validator</a>\n  9.9.9 &middot; schema 1.1" in html


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
