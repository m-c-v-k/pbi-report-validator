"""Render a ``DiffResult`` as a single self-contained HTML page.

The template source is passed in (``integrations.templates`` reads it), so
this module does no I/O. All CSS and JavaScript are inline; the page makes
no network requests and works offline, as a CI artifact or on GitHub Pages.
"""

from collections import Counter

from jinja2 import Environment, StrictUndefined

from pbi_report_validator.domain.models import Category, DiffResult, Finding
from pbi_report_validator.reporting.labels import (
    CATEGORY_LABELS,
    STATUS_LABELS,
    STATUS_MARKS,
    data_overview,
)

REPORT_TEMPLATE = "report.html.j2"


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
        data_overview=data_overview(result),
        data_by_path={s.path: s for s in result.data},
        details=visual_findings(result),
        visual_key=lambda finding: visual_key(finding, keys),
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
        key = visual_key(finding, keys)
        if key is not None:
            grouped.setdefault(key, []).append(finding)
    return grouped


def visual_key(finding: Finding, keys: set[str]) -> str | None:
    """The ``page/visual`` a finding belongs to, if any.

    Parse issues name their visual; other findings point into it with a path
    that starts with ``page/visual``.
    """
    candidate = finding.visual or "/".join(finding.path.split("/")[:2])
    return candidate if candidate in keys else None
