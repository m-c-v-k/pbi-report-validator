"""Parse a PBIR report definition into the ``Report`` domain model.

Covers report and page filters, pages (order, names, size) and visuals
(type, position, title, fields in each role, visual filters and slicer
selection). A page or visual that cannot be parsed becomes a
``ParseIssue`` and the rest of the report is still parsed.
"""

from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from pbi_report_validator.domain.helpers import visual_path
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
from pbi_report_validator.parsers.quoting import unquote

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
    filters, problems = parse_filters(raw.report.content, FilterLevel.REPORT)
    issues = [ParseIssue(path=raw.report.path, message=m) for m in problems]
    pages: list[Page] = []
    for ordinal, raw_page in enumerate(_ordered_pages(raw)):
        page, page_issues = _parse_page(raw_page, ordinal)
        issues += page_issues
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


def _parse_page(raw: RawPage, ordinal: int) -> tuple[Page | None, list[ParseIssue]]:
    """The page (``None`` if it cannot be parsed) and the issues found in it."""
    # The page's folder name is its id; it is known even if the file is broken.
    if raw.page.error is not None:
        return None, [_unreadable(raw.page, page=raw.name)]
    content = raw.page.content
    page_name = str(content.get("name", raw.name))
    issues: list[ParseIssue] = []
    visuals = []
    for raw_visual in raw.visuals:
        visual, visual_issues = _parse_visual_or_issue(raw_visual, page_name)
        issues += visual_issues
        if visual is not None:
            visuals.append(visual)
    filters, problems = parse_filters(content, FilterLevel.PAGE)
    issues += [ParseIssue(path=raw.page.path, message=m) for m in problems]
    try:
        page = Page(
            name=page_name,
            display_name=str(content.get("displayName", raw.name)),
            ordinal=ordinal,
            width=content.get("width", DEFAULT_PAGE_WIDTH),
            height=content.get("height", DEFAULT_PAGE_HEIGHT),
            filters=filters,
            visuals=tuple(visuals),
        )
    except ValidationError as exc:
        error = ParseIssue(
            path=raw.page.path, message=_first_error(exc), page=page_name
        )
        return None, [*issues, error]
    return page, issues


def _parse_visual_or_issue(
    raw: RawJsonFile, page_name: str
) -> tuple[Visual | None, list[ParseIssue]]:
    """The visual (``None`` if it cannot be parsed) and its parse issues."""
    # The visual's folder name is its id; it is known even if the file is broken.
    key = visual_path(page_name, PurePosixPath(raw.path).parent.name)
    if raw.error is not None:
        return None, [_unreadable(raw, visual_path=key)]
    visual, problems = _try_parse_visual(raw.content)
    return visual, [
        ParseIssue(path=raw.path, message=m, visual_path=key) for m in problems
    ]


def _try_parse_visual(content: dict[str, Any]) -> tuple[Visual | None, list[str]]:
    """The visual and its problems, or ``None`` and why it could not be parsed."""
    try:
        return parse_visual(content)
    except VisualParseError as exc:
        return None, [str(exc)]
    except ValidationError as exc:
        return None, [_first_error(exc)]


def parse_visual(content: dict[str, Any]) -> tuple[Visual, list[str]]:
    """Parse one ``visual.json``.

    Returns:
        The visual, and a message for each part that was skipped because it
        could not be read without invalidating the whole visual (for example
        an unrecognised field).

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
    filters, problems = parse_filters(content, FilterLevel.VISUAL)
    body = content.get("visual")
    if not isinstance(body, dict):
        group = Visual(
            name=name,
            visual_type=GROUP_VISUAL_TYPE if "visualGroup" in content else "unknown",
            position=_position(position),
            filters=filters,
        )
        return group, problems
    projections, field_problems = _projections(body)
    first_field = projections[0].field if projections else None
    slicer, slicer_problems = parse_slicer_state(body, first_field)
    visual = Visual(
        name=name,
        visual_type=str(body.get("visualType", "unknown")),
        position=_position(position),
        title=_title(body),
        projections=projections,
        filters=filters,
        slicer=slicer,
    )
    return visual, [*problems, *field_problems, *slicer_problems]


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
    return unquote(literal) if isinstance(literal, str) else None


def _projections(body: dict[str, Any]) -> tuple[tuple[Projection, ...], list[str]]:
    """The fields in each role, and a message for each field that was skipped."""
    query = body.get("query")
    query_state = query.get("queryState") if isinstance(query, dict) else None
    if not isinstance(query_state, dict):
        return (), []
    projections = []
    problems = []
    for role, state in query_state.items():
        items = state.get("projections", []) if isinstance(state, dict) else []
        for item in items:
            field = parse_field(item.get("field") if isinstance(item, dict) else None)
            if field is None:
                problems.append(f"unrecognised field in role {role} was skipped")
            else:
                projections.append(Projection(role=role, field=field))
    return tuple(projections), problems


def _unreadable(
    raw: RawJsonFile, visual_path: str | None = None, page: str | None = None
) -> ParseIssue:
    message = f"unreadable: {raw.error}"
    return ParseIssue(
        path=raw.path, message=message, visual_path=visual_path, page=page
    )


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"invalid {location}: {error['msg']}"
