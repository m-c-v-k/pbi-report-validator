"""Parse a semantic model saved as ``model.bim`` (TMSL) into the domain model.

``model.bim`` is the JSON format Power BI Desktop writes when "Store semantic
model using TMDL format" is off. Only what the diff uses is read: tables,
their columns and their measures. An expression is a string or a list of
lines. A table or measure that cannot be read becomes a ``ParseIssue``.
"""

from typing import Any

from pbi_report_validator.domain.helpers import field_key, json_location
from pbi_report_validator.domain.models import (
    Column,
    Measure,
    ParseIssue,
    SemanticModel,
    SourceLocation,
    Table,
)
from pbi_report_validator.domain.raw import RawJsonFile


def parse_bim(raw: RawJsonFile) -> SemanticModel:
    """Parse the tables of a ``model.bim``.

    Args:
        raw: The file as read by ``integrations.files``.

    Returns:
        Tables with their columns and measures, in file order, plus a parse
        issue for the file or any table or measure that could not be read.
    """
    if raw.error is not None:
        return _unreadable(raw, f"unreadable: {raw.error}")
    model = raw.content.get("model")
    tables = model.get("tables") if isinstance(model, dict) else None
    if not isinstance(tables, list):
        return _unreadable(raw, "model.bim has no model.tables list")
    parsed: list[Table] = []
    issues: list[ParseIssue] = []
    for index, entry in enumerate(tables):
        table, table_issues = _read_table(entry, index, raw.path)
        parsed += [table] if table else []
        issues += table_issues
    return SemanticModel(tables=tuple(parsed), issues=tuple(issues))


def _unreadable(raw: RawJsonFile, message: str) -> SemanticModel:
    return SemanticModel(issues=(ParseIssue(path=raw.path, message=message),))


def _read_table(
    entry: Any, index: int, path: str
) -> tuple[Table | None, list[ParseIssue]]:
    """The table at ``index``, or ``None`` and an issue if it has no name."""
    name = entry.get("name") if isinstance(entry, dict) else None
    if not isinstance(name, str):
        return None, [ParseIssue(path=path, message=f"table {index} has no name")]
    columns = tuple(
        Column(name=c["name"], data_type=_text(c.get("dataType")))
        for c in _objects(entry.get("columns"))
        if isinstance(c.get("name"), str)
    )
    measures: list[Measure] = []
    issues: list[ParseIssue] = []
    for position, item in enumerate(_objects(entry.get("measures"))):
        where = json_location(path, "model", "tables", index, "measures", position)
        measure = _read_measure(item, where)
        if measure is not None:
            measures.append(measure)
            continue
        label = item["name"] if isinstance(item.get("name"), str) else f"#{position}"
        key = field_key(name, label)
        message = f"measure {key} has no name or expression"
        issues.append(ParseIssue(path=path, message=message, measure=key))
    return Table(name=name, columns=columns, measures=tuple(measures)), issues


def _read_measure(item: dict[str, Any], where: SourceLocation | None) -> Measure | None:
    """The measure, or ``None`` if it has no name or no expression."""
    name = item.get("name")
    expression = _expression(item.get("expression"))
    if not isinstance(name, str) or not expression:
        return None
    return Measure(name=name, expression=expression, location=where)


def _expression(value: Any) -> str:
    """A TMSL expression: a string, or a list of lines joined by newlines."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(isinstance(line, str) for line in value):
        return "\n".join(value).strip()
    return ""


def _objects(value: Any) -> list[dict[str, Any]]:
    """The JSON objects in ``value`` if it is a list, else none."""
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None
