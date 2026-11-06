"""Parse a report in the legacy format into the ``Report`` domain model.

The legacy format is one JSON document: ``<Name>.Report/report.json`` in a
PBIP project saved without PBIR, and ``Report/Layout`` in ``.pbit`` and
``.pbix`` files. Pages are ``sections`` and visuals are ``visualContainers``;
each container's ``config`` is a JSON-encoded string holding the visual's
name, position and ``singleVisual`` definition. Fields are listed per role
in ``projections`` by ``queryRef`` and defined in the ``Select`` list of the
visual's ``prototypeQuery``, which refers to tables by alias.

Filters (report, page and visual) are JSON-encoded lists in ``filters`` with
the same entries as PBIR, except that the field is called ``expression``.
A slicer's selection is in ``singleVisual.objects``, as in PBIR. Both are
read with the PBIR filter parser.

A section or visual that cannot be parsed becomes a ``ParseIssue`` and the
rest of the report is still parsed. Source locations point to the section
or container in the document; positions inside the encoded strings cannot
be addressed by a JSON pointer.
"""

import json
from typing import Any

from pydantic import ValidationError

from pbi_report_validator.domain.base import SourceLocation
from pbi_report_validator.domain.helpers import json_location, visual_path
from pbi_report_validator.domain.models import (
    Filter,
    FilterLevel,
    Page,
    ParseIssue,
    Projection,
    Report,
    Visual,
)
from pbi_report_validator.domain.raw import RawLegacyReport
from pbi_report_validator.parsers.pbir import (
    DEFAULT_PAGE_HEIGHT,
    DEFAULT_PAGE_WIDTH,
    GROUP_VISUAL_TYPE,
    VisualParseError,
    container_title,
    first_validation_error,
    parse_position,
)
from pbi_report_validator.parsers.pbir_fields import parse_field, unknown_field
from pbi_report_validator.parsers.pbir_filters import parse_filters, parse_slicer_state

SECTIONS = "sections"
FILTERS = "filters"
CONTAINERS = "visualContainers"
NO_SECTIONS = "sections is not a list; no pages were read"
# Keys of a prototypeQuery Select item that name it rather than define it.
SELECT_NAME_KEYS = frozenset({"Name", "NativeReferenceName"})

JsonPath = tuple[str | int, ...]


def parse_legacy_report(raw: RawLegacyReport) -> Report:
    """Parse the filters, pages and visuals of a legacy-format report.

    Args:
        raw: The report document as read by ``integrations.files``.

    Returns:
        The report with pages in display order (by each section's
        ``ordinal``, then document order) and any parse issues. A page's
        ``ordinal`` is its position in that order, counting sections that
        failed to parse.
    """
    file = raw.layout.path
    filters, problems = _filters(raw.layout.content, FilterLevel.REPORT, file, ())
    issues = [ParseIssue(path=file, message=m) for m in problems]
    sections = raw.layout.content.get(SECTIONS)
    if not isinstance(sections, list):
        issues.append(ParseIssue(path=file, message=NO_SECTIONS))
        return Report(filters=filters, issues=tuple(issues))
    pages: list[Page] = []
    for ordinal, index in enumerate(_display_order(sections)):
        page, page_issues = _parse_section(
            sections[index], (SECTIONS, index), ordinal, file
        )
        issues += page_issues
        if page is not None:
            pages.append(page)
    return Report(filters=filters, pages=tuple(pages), issues=tuple(issues))


def _display_order(sections: list[Any]) -> list[int]:
    """Section indexes sorted by ``ordinal``; sections without one go last."""

    def key(index: int) -> tuple[int, int]:
        section = sections[index]
        ordinal = section.get("ordinal") if isinstance(section, dict) else None
        if isinstance(ordinal, int) and not isinstance(ordinal, bool):
            return (ordinal, index)
        return (len(sections), index)

    return sorted(range(len(sections)), key=key)


def _parse_section(
    section: Any, where: JsonPath, ordinal: int, file: str
) -> tuple[Page | None, list[ParseIssue]]:
    """The page (``None`` if it cannot be parsed) and the issues found in it."""
    name = section.get("name") if isinstance(section, dict) else None
    if not isinstance(name, str):
        message = f"section {where[-1]} has no name; page skipped"
        return None, [ParseIssue(path=file, message=message)]
    containers = section.get(CONTAINERS, [])
    if not isinstance(containers, list):
        containers = []
    visuals: list[Visual] = []
    issues: list[ParseIssue] = []
    for index, container in enumerate(containers):
        visual, problems = _parse_container_or_issue(
            container, (*where, CONTAINERS, index), name, file
        )
        issues += problems
        if visual is not None:
            visuals.append(visual)
    filters, filter_problems = _filters(section, FilterLevel.PAGE, file, where)
    issues += [ParseIssue(path=file, message=m) for m in filter_problems]
    try:
        page = Page(
            location=json_location(file, *where),
            name=name,
            display_name=str(section.get("displayName", name)),
            ordinal=ordinal,
            width=section.get("width", DEFAULT_PAGE_WIDTH),
            height=section.get("height", DEFAULT_PAGE_HEIGHT),
            filters=filters,
            visuals=tuple(visuals),
        )
    except ValidationError as exc:
        return None, [
            *issues,
            ParseIssue(path=file, message=first_validation_error(exc), page=name),
        ]
    return page, issues


def _parse_container_or_issue(
    container: Any, where: JsonPath, page_name: str, file: str
) -> tuple[Visual | None, list[ParseIssue]]:
    """The visual (``None`` if it cannot be parsed) and its parse issues."""
    raw_config = container.get("config") if isinstance(container, dict) else None
    config, error = decode(raw_config)
    name = config.get("name") if config is not None else None
    # Without a readable name the container is known by its index only.
    key = visual_path(
        page_name, name if isinstance(name, str) else f"{CONTAINERS}[{where[-1]}]"
    )
    if config is None:
        message = f"visual config is unreadable: {error}"
        return None, [ParseIssue(path=file, message=message, visual_path=key)]
    try:
        visual, problems = parse_container(container, config, file, where)
    except VisualParseError as exc:
        problems, visual = [str(exc)], None
    except ValidationError as exc:
        problems, visual = [first_validation_error(exc)], None
    return visual, [ParseIssue(path=file, message=m, visual_path=key) for m in problems]


def parse_container(
    container: dict[str, Any], config: dict[str, Any], file: str | None, where: JsonPath
) -> tuple[Visual, list[str]]:
    """Parse one visual container whose ``config`` string is already decoded.

    Args:
        container: The ``visualContainers`` entry.
        config: Its decoded ``config``.
        file: The document's path, recorded as the location of the visual
            and its fields; ``None`` records none.
        where: The container's JSON path in the document.

    Returns:
        The visual, and a message for each field, filter or slicer selection
        that could not be fully read.

    Raises:
        VisualParseError: Name or position (x, y, width, height) is missing.
        pydantic.ValidationError: A value is out of range.
    """
    name = config.get("name")
    if not isinstance(name, str):
        raise VisualParseError("visual has no name")
    position = parse_position(_position(config, container))
    location = json_location(file, *where)
    filters, problems = _filters(container, FilterLevel.VISUAL, file, where)
    single = config.get("singleVisual")
    if not isinstance(single, dict):
        visual_type = GROUP_VISUAL_TYPE if "singleVisualGroup" in config else "unknown"
        group = Visual(
            location=location,
            name=name,
            visual_type=visual_type,
            position=position,
            filters=filters,
        )
        return group, problems
    config_location = json_location(file, *where, "config")
    projections, field_problems = _projections(single, config_location)
    first_field = projections[0].field if projections else None
    slicer, slicer_problems = parse_slicer_state(single, first_field)
    visual = Visual(
        location=location,
        name=name,
        visual_type=str(single.get("visualType", "unknown")),
        position=position,
        title=container_title(single.get("vcObjects")),
        projections=projections,
        filters=filters,
        slicer=slicer.model_copy(update={"location": config_location})
        if slicer
        else None,
    )
    return visual, [*problems, *field_problems, *slicer_problems]


def _filters(
    owner: Any, level: FilterLevel, file: str | None, where: JsonPath
) -> tuple[tuple[Filter, ...], list[str]]:
    """The filters in ``owner``'s encoded ``filters`` list, and any problems.

    Every filter is located at the encoded string, since entries inside it
    cannot be addressed by a JSON pointer.
    """
    if not isinstance(owner, dict) or FILTERS not in owner:
        return (), []
    entries, error = _loads(owner[FILTERS])
    if not isinstance(entries, list):
        return (), [f"filters are unreadable: {error or 'not a JSON list'}"]
    filters, problems = parse_filters({"filterConfig": {FILTERS: entries}}, level)
    location = json_location(file, *where, FILTERS)
    return tuple(f.model_copy(update={"location": location}) for f in filters), problems


def _position(config: dict[str, Any], container: dict[str, Any]) -> dict[str, Any]:
    """The first layout's position; the container's own values without one."""
    layouts = config.get("layouts")
    if isinstance(layouts, list) and layouts and isinstance(layouts[0], dict):
        position = layouts[0].get("position")
        if isinstance(position, dict):
            return position
    return container


def _projections(
    single: dict[str, Any], location: SourceLocation | None
) -> tuple[tuple[Projection, ...], list[str]]:
    """The fields in each role, and a message for each field that was skipped."""
    roles = single.get("projections")
    if not isinstance(roles, dict):
        return (), []
    selects, aliases = _query_fields(single.get("prototypeQuery"))
    projections: list[Projection] = []
    problems: list[str] = []
    for role, items in roles.items():
        if not isinstance(items, list):
            problems.append(f"projections in role {role} are not a list, skipped")
            continue
        for item in items:
            ref = item.get("queryRef") if isinstance(item, dict) else None
            expression = selects.get(ref) if isinstance(ref, str) else None
            field = parse_field(expression, aliases) or unknown_field(expression)
            if field is None:
                problems.append(
                    f"field {ref!r} in role {role} is not in the visual's query,"
                    " skipped"
                )
                continue
            projections.append(Projection(role=role, field=field, location=location))
    return tuple(projections), problems


def _query_fields(query: Any) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """The query's field expressions by ``Name``, and its table aliases."""
    if not isinstance(query, dict):
        return {}, {}
    sources = query.get("From")
    aliases = {
        s["Name"]: s["Entity"]
        for s in (sources if isinstance(sources, list) else [])
        if isinstance(s, dict)
        and isinstance(s.get("Name"), str)
        and isinstance(s.get("Entity"), str)
    }
    items = query.get("Select")
    selects = {
        s["Name"]: {k: v for k, v in s.items() if k not in SELECT_NAME_KEYS}
        for s in (items if isinstance(items, list) else [])
        if isinstance(s, dict) and isinstance(s.get("Name"), str)
    }
    return selects, aliases


def decode(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Decode a JSON-encoded object string, or ``None`` and why it failed."""
    decoded, error = _loads(value)
    if error is not None:
        return None, error
    if not isinstance(decoded, dict):
        return None, "not a JSON object"
    return decoded, None


def _loads(value: Any) -> tuple[Any, str | None]:
    """The value of a JSON-encoded string, or ``None`` and why it failed."""
    if not isinstance(value, str):
        return None, "not a JSON string"
    try:
        return json.loads(value), None
    except json.JSONDecodeError as exc:
        return None, str(exc)
