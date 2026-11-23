"""Render a ``DiffResult`` as Markdown for pull request comments.

Findings are grouped by category. Short old/new values are shown inline;
long or multi-line values (such as DAX expressions) go into collapsible
``<details>`` blocks. The text is kept under GitHub's comment size limit
by dropping whole findings from the end and saying how many were left out.

A ``changed`` run over several projects gets one table of projects, then
each compared project's findings in a collapsible block; projects that no
longer fit are named in a note.
"""

import html
import re
from collections import Counter

from pbi_report_validator.domain.models import (
    Category,
    ChangedResult,
    DiffResult,
    Finding,
    ProjectRun,
)
from pbi_report_validator.reporting.labels import (
    ATTRIBUTION_HEADING,
    CATEGORY_LABELS,
    UNMASKED_WARNING,
    ai_explanation,
    ai_notes,
    ai_overview,
    attribution_lines,
    data_overview,
    severity_overview,
)

GITHUB_COMMENT_LIMIT = 65_536
SAFETY_MARGIN = 1_000
INLINE_VALUE_LIMIT = 80
TITLE = "## Power BI report diff"
PROJECT_TABLE = (
    "| Project | Status | Critical | Warning | Info |",
    "|---|---|---:|---:|---:|",
)
SEE_JSON = "see the JSON output for the full list."
NO_MENTION = "@​"
MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]|<>#~])")


def to_markdown(
    result: DiffResult, limit: int = GITHUB_COMMENT_LIMIT, title: str | None = TITLE
) -> str:
    """Render the result as GitHub-flavoured Markdown.

    Args:
        result: The diff result.
        limit: Maximum length in characters; findings beyond it are left
            out with a note.
        title: The heading on top; ``None`` leaves it out.

    Returns:
        Markdown text ending with a newline.
    """
    header = _header(result, title)
    if not result.findings:
        return f"{header}No differences found.\n"
    budget = limit - SAFETY_MARGIN - len(header)
    sections: list[str] = []
    shown = 0
    current: Category | None = None
    notes = ai_notes(result)
    for finding in _grouped(result.findings):
        block = (
            _finding(finding)
            + _note(ai_explanation(finding))
            + _note(notes.get((finding.category, finding.path)))
        )
        if finding.category != current:
            block = f"\n### {CATEGORY_LABELS[finding.category]}\n\n{block}"
        if len(block) > budget:
            break
        sections.append(block)
        budget -= len(block)
        current = finding.category
        shown += 1
    hidden = len(result.findings) - shown
    noun = "finding" if hidden == 1 else "findings"
    footer = f"\n_{hidden} more {noun} not shown; {SEE_JSON}_\n" if hidden else ""
    return header + "".join(sections) + footer


def changed_to_markdown(
    result: ChangedResult, limit: int = GITHUB_COMMENT_LIMIT
) -> str:
    """Render a ``changed`` run: a table of projects, then each one's findings.

    Compared projects are detailed in path order. Each gets an equal share of
    the space left within ``limit``, so one large project cannot crowd out
    the others; space a project does not use goes to the ones after it.
    Projects whose summary no longer fits are counted in a note at the end.
    """
    header = _changed_header(result)
    compared = [(run.path, run.result) for run in result.projects if run.result]
    budget = limit - SAFETY_MARGIN - len(header)
    blocks: list[str] = []
    for index, (path, project) in enumerate(compared):
        block = _project_block(path, project, budget // (len(compared) - index))
        if len(block) > budget:
            break
        blocks.append(block)
        budget -= len(block)
    hidden = len(compared) - len(blocks)
    noun = "project" if hidden == 1 else "projects"
    footer = f"\n_{hidden} more {noun} not shown in detail; {SEE_JSON}_\n"
    return header + "".join(blocks) + (footer if hidden else "")


def _changed_header(result: ChangedResult) -> str:
    lines = [f"{TITLE}: changed since `{_code(result.base)}`", ""]
    if not result.projects:
        return "\n".join([*lines, "No reports or semantic models changed."]) + "\n"
    noun = "project" if len(result.projects) == 1 else "projects"
    lines += [
        f"{len(result.projects)} {noun} · Severity: {severity_overview(result)}",
        "",
        *PROJECT_TABLE,
        *[_project_row(run) for run in result.projects],
        "",
    ]
    lines += [
        f"- `{_code(run.path)}` ({run.status.value}): {_unmentionable(run.message)}"
        for run in result.projects
        if run.message
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _project_row(run: ProjectRun) -> str:
    path = _code(run.path).replace("|", r"\|")
    counts = run.result.severity_counts if run.result else None
    cells = [counts.critical, counts.warning, counts.info] if counts else ["", "", ""]
    return f"| `{path}` | {run.status.value} | " + " | ".join(map(str, cells)) + " |"


def _project_block(path: str, result: DiffResult, budget: int) -> str:
    """One compared project's findings, collapsed under its path."""
    count = len(result.findings)
    noun = "finding" if count == 1 else "findings"
    summary = f"<code>{html.escape(path)}</code> · {count} {noun}"
    body = to_markdown(result, limit=budget, title=None)
    return f"\n<details><summary>{summary}</summary>\n\n{body}\n</details>\n"


def _header(result: DiffResult, title: str | None) -> str:
    counts = Counter(f.category for f in result.findings)
    lines: list[str] = []
    if result.data_values_shown:
        lines += ["> [!WARNING]", f"> **Unmasked data.** {UNMASKED_WARNING}", ""]
    if title is not None:
        lines += [title, ""]
    lines += [
        f"`{_code(result.old_source)}` → `{_code(result.new_source)}`"
        f" · {len(result.findings)} findings",
        "",
    ]
    if result.findings:
        lines += [f"Severity: {severity_overview(result)}", ""]
    for overview in (data_overview(result), ai_overview(result)):
        if overview:
            lines += [overview, ""]
    if causes := attribution_lines(result):
        lines += [ATTRIBUTION_HEADING, ""]
        lines += [f"- `{_code(p)}`: {_unmentionable(c)}" for p, c in causes]
        lines.append("")
    if result.findings:
        lines += ["| Category | Findings |", "|---|---:|"]
        lines += [
            f"| {CATEGORY_LABELS[c]} | {counts[c]} |" for c in Category if counts[c]
        ]
    return "\n".join(lines) + "\n"


def _grouped(findings: tuple[Finding, ...]) -> list[Finding]:
    order = {c: i for i, c in enumerate(Category)}
    return sorted(findings, key=lambda f: (order[f.category], f.sort_key))


def _finding(finding: Finding) -> str:
    path = _code(finding.path)
    message = _unmentionable(" ".join(finding.message.split()))
    line = (
        f"- {finding.severity.value} · **{finding.change.value}** `{path}`: {message}"
    )
    if finding.old is None and finding.new is None:
        return line + "\n"
    if _is_short(finding.old) and _is_short(finding.new):
        return f"{line} ({_inline(finding.old)} → {_inline(finding.new)})\n"
    return line + "\n" + _details(finding.old, finding.new)


def _note(note: str | None) -> str:
    """An AI note under a finding."""
    if not note:
        return ""
    return f"  - _{_unmentionable(note)}_\n"


def _unmentionable(text: str) -> str:
    """Escaped text in which a zero-width space keeps "@" from mentioning."""
    return escape(text).replace("@", NO_MENTION)


def _details(old: str | None, new: str | None) -> str:
    parts = ["  <details><summary>Old → new</summary>", ""]
    for label, value in (("Old", old), ("New", new)):
        parts.append(f"  {label}:")
        parts.append("")
        if value is None:
            parts.append("  _(none)_")
        else:
            fence = _fence(value)
            parts += [
                f"  {fence}",
                *[f"  {v}" for v in value.splitlines()],
                f"  {fence}",
            ]
        parts.append("")
    parts.append("  </details>")
    return "\n".join(parts) + "\n"


def _fence(value: str) -> str:
    """A backtick fence longer than any backtick run inside ``value``."""
    longest = max((len(run) for run in re.findall(r"`+", value)), default=0)
    return "`" * max(3, longest + 1)


def _is_short(value: str | None) -> bool:
    return value is None or ("\n" not in value and len(value) <= INLINE_VALUE_LIMIT)


def _inline(value: str | None) -> str:
    return "_(none)_" if value is None else f"`{_code(value)}`"


def _code(value: str) -> str:
    """Make a value safe inside single backticks."""
    return value.replace("`", "'")


def escape(text: str) -> str:
    """Escape Markdown and HTML special characters in plain text.

    ``&`` becomes ``&amp;`` (a backslash does not stop entity decoding);
    the other special characters get a backslash.
    """
    return MARKDOWN_SPECIAL.sub(r"\\\1", text.replace("&", "&amp;"))
