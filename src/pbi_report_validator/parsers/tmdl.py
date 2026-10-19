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
from dataclasses import dataclass

from pbi_report_validator.domain.helpers import field_key
from pbi_report_validator.domain.models import (
    Column,
    Measure,
    ParseIssue,
    SemanticModel,
    Table,
)
from pbi_report_validator.domain.raw import RawSemanticModel
from pbi_report_validator.parsers.quoting import unquote

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
    tables: list[Table] = []
    issues: list[ParseIssue] = []
    for header, body in _blocks(_split_lines(text), depth=0):
        match = OBJECT_LINE.match(header.text)
        if match and match["kind"] == "table":
            table, table_issues = _read_table(unquote(match["name"]), body, path)
            tables.append(table)
            issues += table_issues
    return tables, issues


def _read_table(
    name: str, lines: list[_Line], path: str
) -> tuple[Table, list[ParseIssue]]:
    """A table from the lines below its ``table`` line; other objects are skipped."""
    columns: list[Column] = []
    measures: list[Measure] = []
    issues: list[ParseIssue] = []
    for header, body in _blocks(lines, depth=1):
        match = OBJECT_LINE.match(header.text)
        if match and match["kind"] == "column":
            columns.append(_read_column(match, header, body))
        elif match and match["kind"] == "measure":
            measure = _read_measure(match, header, body)
            if measure is None:
                key = field_key(name, unquote(match["name"]))
                issues.append(
                    ParseIssue(
                        path=f"{path}:{header.number}",
                        message=f"measure {key} has no expression",
                    )
                )
            else:
                measures.append(measure)
    table = Table(name=name, columns=tuple(columns), measures=tuple(measures))
    return table, issues


def _read_measure(
    match: re.Match[str], header: _Line, body: list[_Line]
) -> Measure | None:
    """The measure, or ``None`` if it has no expression."""
    expression = (
        _expression(match["expr"], body, header.depth) if match["assign"] else ""
    )
    if not expression:
        return None
    return Measure(name=unquote(match["name"]), expression=expression)


def _read_column(match: re.Match[str], header: _Line, body: list[_Line]) -> Column:
    data_type = None
    for line in body:
        type_match = DATA_TYPE_LINE.match(line.text)
        if line.depth == header.depth + 1 and type_match:
            data_type = type_match["value"]
    return Column(name=unquote(match["name"]), data_type=data_type)


def _blocks(lines: list[_Line], depth: int) -> list[tuple[_Line, list[_Line]]]:
    """Split lines into objects: each line at ``depth`` with the lines below it.

    Deeper lines before the first line at ``depth`` belong to no object and
    are dropped.
    """
    blocks: list[tuple[_Line, list[_Line]]] = []
    for line in lines:
        if line.depth == depth:
            blocks.append((line, []))
        elif line.depth > depth and blocks:
            blocks[-1][1].append(line)
    return blocks


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
