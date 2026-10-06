"""Parse a PBIR report definition into the ``Report`` domain model.

Covers report and page filters, pages (order, names, size) and visuals
(type, position, title, fields in each role, visual filters and slicer
selection). A page or visual that cannot be parsed becomes a
``ParseIssue`` and the rest of the report is still parsed.
"""

from typing import Any

from pydantic import ValidationError

from pbi_report_validator.domain.models import (
    FilterLevel,
    Page,
    ParseIssue,
    Position,
    Projection,
    Report,
    Visual,
)
from pbi_report_validator.domain.raw import RawJsonFile, RawPage, RawReport
from pbi_report_validator.parsers.pbir_fields import parse_field
from pbi_report_validator.parsers.pbir_filters import (
    parse_filters,
    parse_slicer_state,
)

DEFAULT_PAGE_WIDTH = 1280.0
DEFAULT_PAGE_HEIGHT = 720.0
GROUP_VISUAL_TYPE = "group"
REQUIRED_POSITION_KEYS = ("x", "y", "width", "height")


class VisualParseError(ValueError):
    """A visual or page definition is missing required parts."""


def parse_report(raw: RawReport) -> Report:
    """Parse the filters, pages and visuals of a PBIR report.

    Args:
        raw: The report folder contents as read by ``integrations.files``.

    Returns:
        The report with pages in display order and any parse issues. A
        page's ``ordinal`` is its position in ``pages.json``, counting pages
        that failed to parse, so it stays stable when one page breaks.
    """
    issues: list[ParseIssue] = []
    problems: list[str] = []
    filters = parse_filters(raw.report.content, FilterLevel.REPORT, problems)
    issues.extend(ParseIssue(path=raw.report.path, message=m) for m in problems)
    pages: list[Page] = []
    for ordinal, raw_page in enumerate(_ordered_pages(raw)):
        page = _parse_page(raw_page, ordinal, issues)
        if page is not None:
            pages.append(page)
    return Report(filters=filters, pages=tuple(pages), issues=tuple(issues))


def _ordered_pages(raw: RawReport) -> list[RawPage]:
    """Pages in ``pages.json`` order; unlisted pages follow, sorted by name."""
    order = raw.pages_meta.content.get("pageOrder", []) if raw.pages_meta else []
    names = [name for name in order if isinstance(name, str)]
    position = {name: i for i, name in enumerate(names)}
    return sorted(
        raw.pages, key=lambda p: (position.get(p.name, len(position)), p.name)
    )


def _parse_page(raw: RawPage, ordinal: int, issues: list[ParseIssue]) -> Page | None:
    content = _content_or_issue(raw.page, issues)
    if content is None:
        return None
    visuals = []
    for raw_visual in raw.visuals:
        visual = _parse_visual_or_issue(raw_visual, issues)
        if visual is not None:
            visuals.append(visual)
    problems: list[str] = []
    filters = parse_filters(content, FilterLevel.PAGE, problems)
    issues.extend(ParseIssue(path=raw.page.path, message=m) for m in problems)
    try:
        return Page(
            name=str(content.get("name", raw.name)),
            display_name=str(content.get("displayName", raw.name)),
            ordinal=ordinal,
            width=content.get("width", DEFAULT_PAGE_WIDTH),
            height=content.get("height", DEFAULT_PAGE_HEIGHT),
            filters=filters,
            visuals=tuple(visuals),
        )
    except ValidationError as exc:
        issues.append(ParseIssue(path=raw.page.path, message=_first_error(exc)))
        return None


def _parse_visual_or_issue(raw: RawJsonFile, issues: list[ParseIssue]) -> Visual | None:
    content = _content_or_issue(raw, issues)
    if content is None:
        return None
    problems: list[str] = []
    try:
        visual = parse_visual(content, problems)
    except VisualParseError as exc:
        issues.append(ParseIssue(path=raw.path, message=str(exc)))
    except ValidationError as exc:
        issues.append(ParseIssue(path=raw.path, message=_first_error(exc)))
    else:
        issues.extend(ParseIssue(path=raw.path, message=m) for m in problems)
        return visual
    return None


def parse_visual(content: dict[str, Any], problems: list[str]) -> Visual:
    """Parse one ``visual.json``.

    Parts that cannot be read without invalidating the whole visual (for
    example an unrecognised field) are skipped and described in
    ``problems``.

    Raises:
        VisualParseError: Name or position (x, y, width, height) is missing.
        pydantic.ValidationError: A value is out of range.
    """
    name = content.get("name")
    position = content.get("position")
    if not isinstance(name, str) or not isinstance(position, dict):
        raise VisualParseError("visual has no name or position")
    missing = [key for key in REQUIRED_POSITION_KEYS if key not in position]
    if missing:
        raise VisualParseError(f"visual position is missing {', '.join(missing)}")
    body = content.get("visual")
    if not isinstance(body, dict):
        return Visual(
            name=name,
            visual_type=GROUP_VISUAL_TYPE if "visualGroup" in content else "unknown",
            position=_position(position),
            filters=parse_filters(content, FilterLevel.VISUAL, problems),
        )
    projections = _projections(body, problems)
    first_field = projections[0].field if projections else None
    return Visual(
        name=name,
        visual_type=str(body.get("visualType", "unknown")),
        position=_position(position),
        title=_title(body),
        projections=projections,
        filters=parse_filters(content, FilterLevel.VISUAL, problems),
        slicer=parse_slicer_state(body, first_field, problems),
    )


def _position(position: dict[str, Any]) -> Position:
    return Position(
        x=position["x"],
        y=position["y"],
        z=position.get("z", 0),
        width=position["width"],
        height=position["height"],
    )


def _title(body: dict[str, Any]) -> str | None:
    try:
        value = body["visualContainerObjects"]["title"][0]["properties"]["text"]
        literal = value["expr"]["Literal"]["Value"]
    except (KeyError, IndexError, TypeError):
        return None
    return _unquote_literal(literal) if isinstance(literal, str) else None


def _projections(body: dict[str, Any], problems: list[str]) -> tuple[Projection, ...]:
    query = body.get("query")
    query_state = query.get("queryState") if isinstance(query, dict) else None
    if not isinstance(query_state, dict):
        return ()
    projections = []
    for role, state in query_state.items():
        items = state.get("projections", []) if isinstance(state, dict) else []
        for item in items:
            field = parse_field(item.get("field") if isinstance(item, dict) else None)
            if field is None:
                problems.append(f"unrecognised field in role {role} was skipped")
            else:
                projections.append(Projection(role=role, field=field))
    return tuple(projections)


def _content_or_issue(
    raw: RawJsonFile, issues: list[ParseIssue]
) -> dict[str, Any] | None:
    if raw.error is not None:
        issues.append(ParseIssue(path=raw.path, message=f"unreadable: {raw.error}"))
        return None
    return raw.content


def _unquote_literal(value: str) -> str:
    """Strip PBIR string literal quotes: ``'Total sales'`` -> ``Total sales``."""
    if len(value) >= 2 and value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    return value


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"invalid {location}: {error['msg']}"
