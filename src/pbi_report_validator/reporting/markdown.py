"""Render a ``DiffResult`` as Markdown for pull request comments.

Findings are grouped by category. Short old/new values are shown inline;
long or multi-line values (such as DAX expressions) go into collapsible
``<details>`` blocks. The text is kept under GitHub's comment size limit
by dropping whole findings from the end and saying how many were left out.
"""

import re

from pbi_report_validator.domain.models import Category, DiffResult, Finding

GITHUB_COMMENT_LIMIT = 65_536
SAFETY_MARGIN = 1_000
INLINE_VALUE_LIMIT = 80
TITLE = "## Power BI report diff"
SEE_JSON = "see the JSON output for the full list."
CATEGORY_TITLES = {
    Category.PAGE: "Pages",
    Category.VISUAL: "Visuals",
    Category.FIELD: "Fields",
    Category.FILTER: "Filters",
    Category.SLICER: "Slicers",
    Category.MEASURE: "Measures",
    Category.PARSE_ISSUE: "Parse issues",
}
MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]|<>#~])")


def to_markdown(result: DiffResult, limit: int = GITHUB_COMMENT_LIMIT) -> str:
    """Render the result as GitHub-flavoured Markdown.

    Args:
        result: The diff result.
        limit: Maximum length in characters; findings beyond it are left
            out with a note.

    Returns:
        Markdown text ending with a newline.
    """
    header = _header(result)
    if not result.findings:
        return f"{header}No differences found.\n"
    budget = limit - SAFETY_MARGIN - len(header)
    sections: list[str] = []
    shown = 0
    current: Category | None = None
    for finding in _grouped(result.findings):
        block = _finding(finding)
        if finding.category != current:
            block = f"\n### {CATEGORY_TITLES[finding.category]}\n\n{block}"
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


def _header(result: DiffResult) -> str:
    counts = {c: 0 for c in Category}
    for finding in result.findings:
        counts[finding.category] += 1
    lines = [
        TITLE,
        "",
        f"`{_code(result.old_source)}` → `{_code(result.new_source)}`"
        f" · {len(result.findings)} findings",
        "",
    ]
    if result.findings:
        lines += ["| Category | Findings |", "|---|---:|"]
        lines += [f"| {CATEGORY_TITLES[c]} | {n} |" for c, n in counts.items() if n]
    return "\n".join(lines) + "\n"


def _grouped(findings: tuple[Finding, ...]) -> list[Finding]:
    order = {c: i for i, c in enumerate(Category)}
    return sorted(findings, key=lambda f: (order[f.category], f.sort_key))


def _finding(finding: Finding) -> str:
    path = _code(finding.path)
    message = escape(" ".join(finding.message.split()))
    line = f"- **{finding.change.value}** `{path}`: {message}"
    if finding.old is None and finding.new is None:
        return line + "\n"
    if _is_short(finding.old) and _is_short(finding.new):
        return f"{line} ({_inline(finding.old)} → {_inline(finding.new)})\n"
    return line + "\n" + _details(finding.old, finding.new)


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
