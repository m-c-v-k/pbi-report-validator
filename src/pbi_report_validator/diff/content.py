"""Diff what matched visuals show and how the report is filtered.

Covers fields per visual, filters at report, page and visual level and
slicer selections. Field keys and conditions on the old side are first
rewritten through the measure rename map, so a renamed measure is not
reported again for every visual or filter that uses it.
"""

import re
from collections.abc import Mapping

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
                f"{page}/{visual_match.old.name}", visual_match, renames
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
    old_condition = _rename_in(old.condition, renames) if old else None
    new_condition = new.condition if new else None
    if old_condition == new_condition:
        return None
    if old and new:
        change, message = ChangeKind.MODIFIED, "Slicer selection changed"
    elif new:
        change, message = ChangeKind.ADDED, "Slicer selection added"
    else:
        change, message = ChangeKind.REMOVED, "Slicer selection removed"
    return Finding(
        category=Category.SLICER,
        change=change,
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
    new_roles = _roles_by_field(new, renames)
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
            Finding(
                category=Category.FIELD,
                change=change,
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
    old_by_name = {f.name: _rename_in(f.condition, renames) for f in old}
    new_by_name = {f.name: f.condition for f in new}
    findings = []
    for name in sorted(old_by_name.keys() | new_by_name.keys()):
        path = f"{owner}/filters/{name}"
        if name not in new_by_name:
            change, message = ChangeKind.REMOVED, f"Filter {name} removed"
        elif name not in old_by_name:
            change, message = ChangeKind.ADDED, f"Filter {name} added"
        elif old_by_name[name] != new_by_name[name]:
            change, message = ChangeKind.MODIFIED, f"Filter {name} changed"
        else:
            continue
        findings.append(
            Finding(
                category=Category.FILTER,
                change=change,
                path=path,
                message=message,
                old=old_by_name.get(name),
                new=new_by_name.get(name),
            )
        )
    return findings


def _rename_in(condition: str | None, renames: Mapping[str, str]) -> str | None:
    """Replace renamed field keys in one pass.

    A key only matches as a whole reference (``Sales[X]`` does not match
    inside ``OtherSales[X]``), and each key is replaced at most once, so
    chained renames (A to B, B to C) cannot be applied twice.
    """
    if condition is None or not renames:
        return condition
    keys = sorted(renames, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w'])(?:" + "|".join(map(re.escape, keys)) + ")")
    return pattern.sub(lambda m: renames[m.group(0)], condition)
