"""Diff what matched visuals show and how the report is filtered.

Covers fields per visual, filters at report, page and visual level and
slicer selections. Field keys and conditions on the old side are first
rewritten through the measure rename map, so a renamed measure is not
reported again for every visual or filter that uses it. The new side is
never rewritten: a new visual that still uses a measure's old name is a
broken reference and is reported.
"""

from collections.abc import Mapping

from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.conditions import rename_fields, render
from pbi_report_validator.domain.helpers import aggregated, visual_path
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Filter,
    Finding,
    Projection,
    Report,
    ReportMatch,
    SlicerState,
    VisualMatch,
)

REPORT_PATH = "report"


def diff_content(
    old: Report, new: Report, match: ReportMatch, renames: Mapping[str, str]
) -> list[Finding]:
    """Compare filters, fields and slicer selections of two report versions.

    Report filters are always compared; page and visual content only for
    pages and visuals the matcher paired.

    Args:
        old: The old report (for report-level filters).
        new: The new report.
        match: Page and visual pairing from the matcher.
        renames: Old to new field key for renamed measures.
    """
    findings = _diff_filters(REPORT_PATH, old.filters, new.filters, renames)
    for page_match in match.pages:
        page = page_match.old.name
        findings += _diff_filters(
            page, page_match.old.filters, page_match.new.filters, renames
        )
        for visual_match in page_match.visuals:
            findings += _diff_visual(
                visual_path(page, visual_match.old.name), visual_match, renames
            )
    return findings


def _diff_visual(
    path: str, match: VisualMatch, renames: Mapping[str, str]
) -> list[Finding]:
    findings = _diff_fields(path, match.old.projections, match.new.projections, renames)
    findings += _diff_filters(path, match.old.filters, match.new.filters, renames)
    slicer = _diff_slicer(path, match.old.slicer, match.new.slicer, renames)
    return findings + ([slicer] if slicer else [])


def _diff_slicer(
    path: str,
    old: SlicerState | None,
    new: SlicerState | None,
    renames: Mapping[str, str],
) -> Finding | None:
    """Compare slicer selections of a matched visual.

    A slicer appearing or disappearing (the visual changed to or from a
    slicer) is only reported if it carried a selection.
    """
    old_condition = _definition(old, renames) if old else None
    new_condition = _definition(new, {}) if new else None
    if old_condition == new_condition:
        return None
    if old and new:
        change, message = ChangeKind.MODIFIED, "Slicer selection changed"
    elif new:
        change, message = ChangeKind.ADDED, "Slicer selection added"
    else:
        change, message = ChangeKind.REMOVED, "Slicer selection removed"
    return make_finding(
        Category.SLICER,
        change,
        path=path,
        message=message,
        old=old_condition,
        new=new_condition,
    )


def _diff_fields(
    path: str,
    old: tuple[Projection, ...],
    new: tuple[Projection, ...],
    renames: Mapping[str, str],
) -> list[Finding]:
    old_roles = _roles_by_field(old, renames)
    new_roles = _roles_by_field(new, {})
    findings = []
    for key in sorted(old_roles.keys() | new_roles.keys()):
        before, after = old_roles.get(key), new_roles.get(key)
        if before == after:
            continue
        if after is None:
            change, message = ChangeKind.REMOVED, f"Field {key} removed"
        elif before is None:
            change, message = ChangeKind.ADDED, f"Field {key} added"
        else:
            change, message = ChangeKind.MODIFIED, f"Field {key} moved to another role"
        findings.append(
            make_finding(
                Category.FIELD,
                change,
                path=f"{path}/fields/{key}",
                message=message,
                old=before,
                new=after,
            )
        )
    return findings


def _roles_by_field(
    projections: tuple[Projection, ...], renames: Mapping[str, str]
) -> dict[str, str]:
    """Map each field (with aggregation) to its comma-separated roles."""
    roles: dict[str, set[str]] = {}
    for projection in projections:
        field = projection.field
        key = renames.get(field.key, field.key)
        if field.aggregation:
            key = f"{key} ({field.aggregation})"
        roles.setdefault(key, set()).add(projection.role)
    return {key: ", ".join(sorted(r)) for key, r in roles.items()}


def _diff_filters(
    owner: str,
    old: tuple[Filter, ...],
    new: tuple[Filter, ...],
    renames: Mapping[str, str],
) -> list[Finding]:
    old_by_name = {f.name: f for f in old}
    new_by_name = {f.name: f for f in new}
    findings = []
    for name in sorted(old_by_name.keys() | new_by_name.keys()):
        path = f"{owner}/filters/{name}"
        before, after = old_by_name.get(name), new_by_name.get(name)
        finding = _filter_finding(path, name, before, after, renames)
        if finding is not None:
            findings.append(finding)
    return findings


def _filter_finding(
    path: str,
    name: str,
    old: Filter | None,
    new: Filter | None,
    renames: Mapping[str, str],
) -> Finding | None:
    before = _definition(old, renames) if old else None
    after = _definition(new, {}) if new else None
    if old is None or new is None:
        change = ChangeKind.ADDED if old is None else ChangeKind.REMOVED
        message = f"Filter {name} {change.value}"
    elif before != after:
        change, message = ChangeKind.MODIFIED, f"Filter {name} changed"
    elif (key := _field_key(old, renames)) != _field_key(new, {}):
        change = ChangeKind.MODIFIED
        message = f"Filter {name} uses another field"
        before, after = key, _field_key(new, {})
    elif old.filter_type != new.filter_type:
        change, message = ChangeKind.RETYPED, f"Filter {name} changed type"
        before, after = old.filter_type, new.filter_type
    else:
        return None
    return make_finding(
        Category.FILTER, change, path=path, message=message, old=before, new=after
    )


def _definition(item: Filter | SlicerState, renames: Mapping[str, str]) -> str | None:
    """What a filter or slicer selects: its condition or unread definition.

    Renames are applied to the parsed condition, so a key is only replaced
    where it is a field reference (not inside a text literal or a longer
    table name).
    """
    if item.condition is None:
        return item.unread
    if item.expression is None or not renames:
        return item.condition
    return render(rename_fields(item.expression, renames))


def _field_key(item: Filter, renames: Mapping[str, str]) -> str | None:
    if item.field is None:
        return None
    key = renames.get(item.field.key, item.field.key)
    return aggregated(key, item.field.aggregation)
