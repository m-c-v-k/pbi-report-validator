"""Parse TMDL (Tabular Model Definition Language) into a ``SemanticModel``.

Only tables, columns and measures are extracted. Everything else
(relationships, partitions, hierarchies, annotations, roles, calculation
groups, ...) is skipped without error.

TMDL is indentation based: an object's properties are indented one level
deeper than the object, and a multi-line expression one level deeper than
the properties. Blank lines inside an expression are not kept. ``///``
description lines are skipped above expression depth; inside an expression
they are kept as part of the DAX.
"""

import re
from dataclasses import dataclass, field

from pbi_report_validator.domain.models import (
    Column,
    Measure,
    ParseIssue,
    SemanticModel,
    Table,
)
from pbi_report_validator.domain.raw import RawSemanticModel

SPACES_PER_LEVEL = 4
EXPRESSION_DEPTH = 3  # table (0) > measure (1) > properties (2) > expression
FENCE = "```"
OBJECT_LINE = re.compile(
    r"^(?P<kind>table|column|measure)\s+"
    r"(?P<name>'(?:[^']|'')*'|[^\s=]+)"
    r"\s*(?P<assign>=\s*(?P<expr>.*))?$"
)
DATA_TYPE_LINE = re.compile(r"^dataType:\s*(?P<value>\S+)")


@dataclass
class _Line:
    number: int
    depth: int
    text: str
    raw: str


@dataclass
class _TableBuilder:
    name: str
    columns: list[Column] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)

    def build(self) -> Table:
        return Table(
            name=self.name, columns=tuple(self.columns), measures=tuple(self.measures)
        )


def parse_semantic_model(raw: RawSemanticModel) -> SemanticModel:
    """Parse all ``.tmdl`` files of a semantic model.

    Args:
        raw: The model's TMDL files as read by ``integrations.files``.

    Returns:
        Tables with their columns and measures, in file order, plus a parse
        issue for every object that could not be read.
    """
    tables: list[Table] = []
    issues: list[ParseIssue] = []
    for file in raw.files:
        file_tables, file_issues = parse_tmdl(file.text, file.path)
        tables.extend(file_tables)
        issues.extend(file_issues)
    return SemanticModel(tables=tuple(tables), issues=tuple(issues))


def parse_tmdl(text: str, path: str) -> tuple[list[Table], list[ParseIssue]]:
    """Parse the tables defined in one TMDL document.

    Args:
        text: The TMDL source.
        path: File path, used in parse issues.

    Returns:
        The tables found and any parse issues.
    """
    lines = _split_lines(text)
    tables: list[Table] = []
    issues: list[ParseIssue] = []
    current: _TableBuilder | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        match = OBJECT_LINE.match(line.text)
        if line.depth == 0:
            if current:
                tables.append(current.build())
            is_table = match is not None and match["kind"] == "table"
            current = (
                _TableBuilder(_unquote(match["name"])) if match and is_table else None
            )
            index += 1
        elif current and line.depth == 1 and match and match["kind"] == "measure":
            index = _read_measure(lines, index, match, current, path, issues)
        elif current and line.depth == 1 and match and match["kind"] == "column":
            index = _read_column(lines, index, match, current)
        else:
            index += 1
    if current:
        tables.append(current.build())
    return tables, issues


def _read_measure(
    lines: list[_Line],
    index: int,
    match: re.Match[str],
    table: _TableBuilder,
    path: str,
    issues: list[ParseIssue],
) -> int:
    name = _unquote(match["name"])
    start = lines[index]
    body, index = _collect_body(lines, index + 1, start.depth)
    expression = (
        _expression(match["expr"], body, start.depth) if match["assign"] else ""
    )
    if not expression:
        issues.append(
            ParseIssue(
                path=f"{path}:{start.number}",
                message=f"measure {table.name}[{name}] has no expression",
            )
        )
        return index
    table.measures.append(Measure(name=name, expression=expression))
    return index


def _read_column(
    lines: list[_Line], index: int, match: re.Match[str], table: _TableBuilder
) -> int:
    start = lines[index]
    body, index = _collect_body(lines, index + 1, start.depth)
    data_type = None
    for line in body:
        type_match = DATA_TYPE_LINE.match(line.text)
        if line.depth == start.depth + 1 and type_match:
            data_type = type_match["value"]
    table.columns.append(Column(name=_unquote(match["name"]), data_type=data_type))
    return index


def _collect_body(
    lines: list[_Line], index: int, object_depth: int
) -> tuple[list[_Line], int]:
    """Return the lines indented below an object and the index after them."""
    body: list[_Line] = []
    while index < len(lines) and lines[index].depth > object_depth:
        body.append(lines[index])
        index += 1
    return body, index


def _expression(first: str, body: list[_Line], object_depth: int) -> str:
    """Join the inline part and the deeper-indented lines of an expression."""
    expression_depth = object_depth + 2
    parts = [first.strip()] if first.strip() else []
    for line in body:
        if line.depth < expression_depth:
            break
        parts.append(_dedent(line, expression_depth))
    text = "\n".join(parts).strip()
    if text.startswith(FENCE) and text.endswith(FENCE) and len(text) > 2 * len(FENCE):
        text = text[len(FENCE) : -len(FENCE)].strip()
    return text


def _split_lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        depth = _depth(raw)
        is_description = stripped.startswith("///") and depth < EXPRESSION_DEPTH
        if not stripped or is_description:
            continue
        lines.append(_Line(number=number, depth=depth, text=stripped, raw=raw.rstrip()))
    return lines


def _depth(raw: str) -> int:
    tabs = len(raw) - len(raw.lstrip("\t"))
    spaces = len(raw[tabs:]) - len(raw[tabs:].lstrip(" "))
    return tabs + spaces // SPACES_PER_LEVEL


def _dedent(line: _Line, depth: int) -> str:
    """Remove ``depth`` levels of indentation, keeping any further indentation."""
    text = line.raw
    for _ in range(depth):
        if text.startswith("\t"):
            text = text[1:]
        elif text.startswith(" " * SPACES_PER_LEVEL):
            text = text[SPACES_PER_LEVEL:]
    return text


def _unquote(name: str) -> str:
    if len(name) >= 2 and name.startswith("'") and name.endswith("'"):
        return name[1:-1].replace("''", "'")
    return name
