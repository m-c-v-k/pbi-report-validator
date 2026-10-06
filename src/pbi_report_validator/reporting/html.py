"""Render a ``DiffResult`` as a single self-contained HTML page.

The template source is passed in (``integrations.templates`` reads it), so
this module does no I/O. All CSS and JavaScript are inline; the page makes
no network requests and works offline, as a CI artifact or on GitHub Pages.
"""

from collections import Counter

from jinja2 import Environment, StrictUndefined

from pbi_report_validator.domain.models import Category, DiffResult

REPORT_TEMPLATE = "report.html.j2"
CATEGORY_LABELS = {
    Category.PAGE: "Pages",
    Category.VISUAL: "Visuals",
    Category.FIELD: "Fields",
    Category.FILTER: "Filters",
    Category.SLICER: "Slicers",
    Category.MEASURE: "Measures",
    Category.PARSE_ISSUE: "Parse issues",
}


def to_html(result: DiffResult, template_source: str, tool_version: str) -> str:
    """Render the HTML report.

    Args:
        result: The diff result.
        template_source: Source of ``report.html.j2``.
        tool_version: Version shown in the page footer.

    Returns:
        The complete HTML document. The same input always gives the same
        output (no timestamps).
    """
    environment = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    counts = Counter(f.category for f in result.findings)
    return environment.from_string(template_source).render(
        result=result,
        tool_version=tool_version,
        categories=[
            (c.value, CATEGORY_LABELS[c], counts[c]) for c in Category if counts[c]
        ],
        labels={c.value: CATEGORY_LABELS[c] for c in Category},
    )
