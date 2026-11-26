"""Render a ``DiffResult`` or ``ChangedResult`` as one self-contained HTML page.

The template source is passed in (``integrations.templates`` reads it), so
this module does no I/O. All CSS and JavaScript are inline; the page makes
no network requests and works offline, as a CI artifact or on GitHub Pages.
"""

from collections import Counter
from collections.abc import Sequence

from jinja2 import Environment, StrictUndefined

from pbi_report_validator.domain.helpers import visual_path, visual_path_of
from pbi_report_validator.domain.models import (
    SCHEMA_VERSION,
    Category,
    ChangedResult,
    DiffResult,
    Finding,
)
from pbi_report_validator.reporting.labels import (
    CATEGORY_LABELS,
    STATUS_LABELS,
    STATUS_MARKS,
    UNMASKED_WARNING,
    ai_explanation,
    ai_notes,
    ai_overview,
    attribution_label,
    data_overview,
    source_locations,
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
    single = _project_context(result, "Power BI report diff")
    return _render(template_source, tool_version, single=single)


def changed_to_html(
    result: ChangedResult, template_source: str, tool_version: str
) -> str:
    """Render a ``changed`` run: an index of projects, then each one's report.

    Every compared project gets the same sections as ``to_html`` in one
    page, with its IDs prefixed so links stay within the project.
    """
    projects = [
        {**_project_context(run.result, run.path), "index": index}
        for index, run in enumerate(result.projects, start=1)
        if run.result is not None
    ]
    return _render(template_source, tool_version, changed=result, projects=projects)


def _render(template_source: str, tool_version: str, **context: object) -> str:
    environment = Environment(
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    defaults: dict[str, object] = {"single": None, "changed": None, "projects": []}
    return environment.from_string(template_source).render(
        **(defaults | context),
        ai_explanation=ai_explanation,
        attribution_label=attribution_label,
        source_locations=source_locations,
        tool_version=tool_version,
        schema_version=SCHEMA_VERSION,
        unmasked_warning=UNMASKED_WARNING,
        labels={c.value: CATEGORY_LABELS[c] for c in Category},
        status_labels={s.value: label for s, label in STATUS_LABELS.items()},
        status_marks={s.value: mark for s, mark in STATUS_MARKS.items()},
    )


def _project_context(result: DiffResult, title: str) -> dict[str, object]:
    """What the template's ``project_report`` macro needs for one result."""
    counts = Counter(f.category for f in result.findings)
    keys = {visual_path(p.name, v.name) for p in result.pages for v in p.visuals}
    return {
        "title": title,
        "result": result,
        "data_overview": data_overview(result),
        "ai_overview": ai_overview(result),
        "ai_notes": ai_notes(result),
        "data_by_path": {s.path: s for s in result.data},
        "details": visual_findings(result.findings, keys),
        "visual_key": lambda finding: visual_key(finding, keys),
        "categories": [
            (c.value, CATEGORY_LABELS[c], counts[c]) for c in Category if counts[c]
        ],
        "severities": list(result.severity_counts.model_dump().items()),
    }


def visual_findings(
    findings: Sequence[Finding], keys: set[str]
) -> dict[str, list[Finding]]:
    """Group findings by the visual they belong to (``page/visual``).

    Includes findings inside a visual (fields, filters) and parse issues on
    its ``visual.json``. Findings not tied to one of ``keys`` are left out.
    """
    grouped: dict[str, list[Finding]] = {}
    for finding in findings:
        key = visual_key(finding, keys)
        if key is not None:
            grouped.setdefault(key, []).append(finding)
    return grouped


def visual_key(finding: Finding, keys: set[str]) -> str | None:
    """The ``page/visual`` a finding belongs to, if any.

    Parse issues name their visual; other findings point into it with a path
    that starts with ``page/visual``. Findings outside any page (measures,
    report filters) belong to no visual.
    """
    if finding.visual_path is not None:
        return finding.visual_path if finding.visual_path in keys else None
    if finding.page_path is None:
        return None
    candidate = visual_path_of(finding.page_path)
    return candidate if candidate in keys else None
