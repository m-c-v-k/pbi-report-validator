"""Render a ``DiffResult`` as a single self-contained HTML page.

The template source is passed in (``integrations.templates`` reads it), so
this module does no I/O. All CSS and JavaScript are inline; the page makes
no network requests and works offline, as a CI artifact or on GitHub Pages.
"""

import re
from collections import Counter

from jinja2 import Environment, StrictUndefined

from pbi_report_validator.domain.models import (
    Category,
    DiffResult,
    Finding,
    ItemStatus,
)

REPORT_TEMPLATE = "report.html.j2"
# Parse-issue paths point at the file, e.g. new/.../pages/p/visuals/v/visual.json
VISUAL_FILE = re.compile(
    r"pages/(?P<page>[^/]+)/visuals/(?P<visual>[^/]+)/visual\.json$"
)
CATEGORY_LABELS = {
    Category.PAGE: "Pages",
    Category.VISUAL: "Visuals",
    Category.FIELD: "Fields",
    Category.FILTER: "Filters",
    Category.SLICER: "Slicers",
    Category.MEASURE: "Measures",
    Category.PARSE_ISSUE: "Parse issues",
}
STATUS_LABELS = {
    ItemStatus.ADDED: "Added",
    ItemStatus.REMOVED: "Removed",
    ItemStatus.MODIFIED: "Modified",
    ItemStatus.UNCHANGED: "Unchanged",
}
# A text mark next to the colour, so status is not conveyed by colour alone.
STATUS_MARKS = {
    ItemStatus.ADDED: "+",
    ItemStatus.REMOVED: "-",
    ItemStatus.MODIFIED: "~",
    ItemStatus.UNCHANGED: "",
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
    keys = {f"{p.name}/{v.name}" for p in result.pages for v in p.visuals}
    return environment.from_string(template_source).render(
        details=visual_findings(result),
        visual_key=lambda path: visual_key(path, keys),
        result=result,
        tool_version=tool_version,
        categories=[
            (c.value, CATEGORY_LABELS[c], counts[c]) for c in Category if counts[c]
        ],
        labels={c.value: CATEGORY_LABELS[c] for c in Category},
        status_labels={s.value: label for s, label in STATUS_LABELS.items()},
        status_marks={s.value: mark for s, mark in STATUS_MARKS.items()},
    )


def visual_findings(result: DiffResult) -> dict[str, list[Finding]]:
    """Group findings by the visual they belong to (``page/visual``).

    Includes findings inside a visual (fields, filters) and parse issues on
    its ``visual.json``. Findings not tied to a visual are left out.
    """
    keys = {f"{p.name}/{v.name}" for p in result.pages for v in p.visuals}
    grouped: dict[str, list[Finding]] = {}
    for finding in result.findings:
        key = visual_key(finding.path, keys)
        if key is not None:
            grouped.setdefault(key, []).append(finding)
    return grouped


def visual_key(path: str, keys: set[str]) -> str | None:
    """The ``page/visual`` a finding path points into, if any."""
    file = VISUAL_FILE.search(path)
    candidate = (
        f"{file['page']}/{file['visual']}" if file else "/".join(path.split("/")[:2])
    )
    return candidate if candidate in keys else None
