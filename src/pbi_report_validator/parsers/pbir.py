"""Parse a PBIR report definition into the ``Report`` domain model.

Covers report and page filters, pages (order, names, size) and visuals
(type, position, title, fields in each role, visual filters and slicer
selection). A page or visual that cannot be parsed becomes a
``ParseIssue`` and the rest of the report is still parsed.
"""

from pathlib import PurePosixPath
from typing import Any

from pydantic import ValidationError

from pbi_report_validator.domain.helpers import json_location, visual_path
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
from pbi_report_validator.parsers.pbir_fields import parse_field, unknown_field
from pbi_report_validator.parsers.pbir_filters import (
    parse_filters,
    parse_slicer_state,
)
from pbi_report_validator.parsers.quoting import unquote

DEFAULT_PAGE_WIDTH = 1280.0
DEFAULT_PAGE_HEIGHT = 720.0
GROUP_VISUAL_TYPE = "group"
REQUIRED_POSITION_KEYS = ("x", "y", "width", "height")
MALFORMED_PAGE_ORDER = "pageOrder is not a list of page names; pages sorted by name"


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
    filters, problems = parse_filters(
        raw.report.content, FilterLevel.REPORT, raw.report.path
    )
    issues = [ParseIssue(path=raw.report.path, message=m) for m in problems]
    names, order_issues = _page_order(raw)
    issues += order_issues
    pages: list[Page] = []
    for ordinal, raw_page in enumerate(_ordered_pages(raw, names)):
        page, page_issues = _parse_page(raw_page, ordinal)
        issues += page_issues
        if page is not None:
            pages.append(page)
    return Report(filters=filters, pages=tuple(pages), issues=tuple(issues))


def _page_order(raw: RawReport) -> tuple[list[str], list[ParseIssue]]:
    """The page names in ``pages.json``, or nothing and an issue if malformed."""
    if raw.pages_meta is None:
        return [], []
    order = raw.pages_meta.content.get("pageOrder", [])
    if isinstance(order, list) and all(isinstance(name, str) for name in order):
        return order, []
    return [], [ParseIssue(path=raw.pages_meta.path, message=MALFORMED_PAGE_ORDER)]


def _ordered_pages(raw: RawReport, names: list[str]) -> list[RawPage]:
    """Pages in the order of ``names``; unlisted pages follow, sorted by name."""
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
    filters, problems = parse_filters(content, FilterLevel.PAGE, raw.page.path)
    issues += [ParseIssue(path=raw.page.path, message=m) for m in problems]
    try:
        page = Page(
            location=json_location(raw.page.path),
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
            path=raw.page.path, message=first_validation_error(exc), page=page_name
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
    visual, problems = _try_parse_visual(raw.content, raw.path)
    return visual, [
        ParseIssue(path=raw.path, message=m, visual_path=key) for m in problems
    ]


def _try_parse_visual(
    content: dict[str, Any], file: str
) -> tuple[Visual | None, list[str]]:
    """The visual and its problems, or ``None`` and why it could not be parsed."""
    try:
        return parse_visual(content, file)
    except VisualParseError as exc:
        return None, [str(exc)]
    except ValidationError as exc:
        return None, [first_validation_error(exc)]


def parse_visual(
    content: dict[str, Any], file: str | None = None
) -> tuple[Visual, list[str]]:
    """Parse one ``visual.json``.

    Args:
        content: The file's JSON.
        file: Its path, recorded as the location of the visual and its
            fields, filters and slicer selection; ``None`` records none.

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
    visual_position = parse_position(position)
    filters, problems = parse_filters(content, FilterLevel.VISUAL, file)
    location = json_location(file)
    body = content.get("visual")
    if not isinstance(body, dict):
        group = Visual(
            location=location,
            name=name,
            visual_type=GROUP_VISUAL_TYPE if "visualGroup" in content else "unknown",
            position=visual_position,
            filters=filters,
        )
        return group, problems
    projections, field_problems = _projections(body, file)
    first_field = projections[0].field if projections else None
    slicer, slicer_problems = parse_slicer_state(body, first_field, file)
    visual = Visual(
        location=location,
        name=name,
        visual_type=str(body.get("visualType", "unknown")),
        position=visual_position,
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


def parse_position(position: dict[str, Any]) -> Position:
    """A visual's position from its ``x``, ``y``, ``z``, ``width``, ``height``.

    Raises:
        VisualParseError: x, y, width or height is missing.
        pydantic.ValidationError: A value is out of range.
    """
    missing = [key for key in REQUIRED_POSITION_KEYS if key not in position]
    if missing:
        raise VisualParseError(f"visual position is missing {', '.join(missing)}")
    return _position(position)


def _title(body: dict[str, Any]) -> str | None:
    return container_title(body.get("visualContainerObjects"))


def container_title(objects: Any) -> str | None:
    """The literal title text in a visual's container objects, if any."""
    try:
        value = objects["title"][0]["properties"]["text"]
        literal = value["expr"]["Literal"]["Value"]
    except (KeyError, IndexError, TypeError):
        return None
    return unquote(literal) if isinstance(literal, str) else None


def _projections(
    body: dict[str, Any], file: str | None
) -> tuple[tuple[Projection, ...], list[str]]:
    """The fields in each role, and a message for each field that was skipped.

    Fields of a kind the parser cannot read are kept as unknown fields, so
    the field diff still compares them; only entries that are not a field
    object at all are skipped.
    """
    query = body.get("query")
    query_state = query.get("queryState") if isinstance(query, dict) else None
    if not isinstance(query_state, dict):
        return (), []
    projections = []
    problems = []
    for role, state in query_state.items():
        items = state.get("projections", []) if isinstance(state, dict) else []
        if not isinstance(items, list):
            problems.append(f"projections in role {role} are not a list, skipped")
            continue
        for index, item in enumerate(items):
            raw = item.get("field") if isinstance(item, dict) else None
            field = parse_field(raw) or unknown_field(raw)
            if field is None:
                problems.append(f"unrecognised field in role {role} was skipped")
                continue
            where = ("visual", "query", "queryState", role, "projections", index)
            location = json_location(file, *where)
            projections.append(Projection(role=role, field=field, location=location))
    return tuple(projections), problems


def _unreadable(
    raw: RawJsonFile, visual_path: str | None = None, page: str | None = None
) -> ParseIssue:
    message = f"unreadable: {raw.error}"
    return ParseIssue(
        path=raw.path, message=message, visual_path=visual_path, page=page
    )


def with_issues_by_name(report: Report, other: Report) -> Report:
    """``report`` with page and visual parse issues keyed by name, not folder.

    A file that cannot be read only gives its folder name, but pages and
    visuals are identified by the ``name`` inside, which may differ. The
    name is taken from the object in the same folder: in ``report`` when it
    was parsed (with problems), else in ``other``, the other version.
    """
    names = {**_names_by_folder(other), **_names_by_folder(report)}
    issues = tuple(_issue_by_name(issue, names) for issue in report.issues)
    return report.model_copy(update={"issues": issues})


def _names_by_folder(report: Report) -> dict[tuple[str, ...], str]:
    names: dict[tuple[str, ...], str] = {}
    for page in report.pages:
        located: list[Page | Visual] = [page, *page.visuals]
        for item in located:
            folders = _folders(item.location.file) if item.location else ()
            if folders:
                names[folders] = item.name
    return names


def _issue_by_name(issue: ParseIssue, names: dict[tuple[str, ...], str]) -> ParseIssue:
    folders = _folders(issue.path)
    name = names.get(folders) if folders else None
    if name is None:
        return issue
    if issue.page is not None:
        return issue.model_copy(update={"page": name})
    if issue.visual_path is not None:
        page, _, _ = issue.visual_path.partition("/")
        return issue.model_copy(update={"visual_path": visual_path(page, name)})
    return issue


def _folders(file: str) -> tuple[str, ...]:
    """The folders below ``definition``, e.g. ``("pages", "p", "visuals", "v")``."""
    parts = PurePosixPath(file).parts
    if "definition" not in parts:
        return ()
    return parts[parts.index("definition") + 1 : -1]


def first_validation_error(exc: ValidationError) -> str:
    """The first validation error as ``invalid <field>: <message>``."""
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error["loc"])
    return f"invalid {location}: {error['msg']}"
