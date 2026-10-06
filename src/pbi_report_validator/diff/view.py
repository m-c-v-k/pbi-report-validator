"""Build the page and visual view used by the Markdown and HTML reports.

Every page and visual of both versions appears exactly once, with its
old and new position and a status derived from the match and the
findings. Pure functions only.
"""

from collections.abc import Sequence

from pbi_report_validator.domain.models import (
    ChangeKind,
    Finding,
    ItemStatus,
    Page,
    PageMatch,
    PageView,
    ReportMatch,
    Visual,
    VisualView,
)


def build_page_views(
    match: ReportMatch, findings: Sequence[Finding]
) -> tuple[PageView, ...]:
    """Pages of both versions, ordered by their position in the report.

    Matched pages use the new order; added pages their new position and
    removed pages their old one. Ties sort removed pages last, then by name.
    """
    paths = {f.path for f in findings}
    unmatched = {(f.path, f.change) for f in findings}
    views = [_matched_page(m, paths, unmatched) for m in match.pages]
    views += [_whole_page(p, ItemStatus.ADDED) for p in match.added_pages]
    views += [_whole_page(p, ItemStatus.REMOVED) for p in match.removed_pages]
    return tuple(
        sorted(views, key=lambda v: (v.ordinal, v.status == ItemStatus.REMOVED, v.name))
    )


def _matched_page(
    match: PageMatch, paths: set[str], unmatched: set[tuple[str, ChangeKind]]
) -> PageView:
    page = match.old.name
    visuals = [
        VisualView(
            name=v.old.name,
            visual_type=v.new.visual_type,
            title=v.new.title,
            status=_status_if_changed(f"{page}/{v.old.name}", paths),
            old_position=v.old.position,
            new_position=v.new.position,
        )
        for v in match.visuals
    ]
    visuals += [
        _unmatched_visual(page, v, ChangeKind.REMOVED, unmatched)
        for v in match.removed_visuals
    ]
    visuals += [
        _unmatched_visual(page, v, ChangeKind.ADDED, unmatched)
        for v in match.added_visuals
    ]
    return PageView(
        name=page,
        display_name=match.new.display_name,
        status=_status_if_changed(page, paths),
        ordinal=match.new.ordinal,
        width=match.new.width,
        height=match.new.height,
        visuals=tuple(sorted(visuals, key=lambda v: v.name)),
    )


def _unmatched_visual(
    page: str,
    visual: Visual,
    change: ChangeKind,
    unmatched: set[tuple[str, ChangeKind]],
) -> VisualView:
    """A visual on one side only.

    Without a matching added/removed finding the visual exists in both
    versions but failed to parse in one; it is shown as modified.
    """
    path = f"{page}/{visual.name}"
    if (path, change) not in unmatched:
        status = ItemStatus.MODIFIED
    else:
        status = ItemStatus.ADDED if change == ChangeKind.ADDED else ItemStatus.REMOVED
    is_old = change == ChangeKind.REMOVED
    return VisualView(
        name=visual.name,
        visual_type=visual.visual_type,
        title=visual.title,
        status=status,
        old_position=visual.position if is_old else None,
        new_position=None if is_old else visual.position,
    )


def _whole_page(page: Page, status: ItemStatus) -> PageView:
    is_old = status == ItemStatus.REMOVED
    return PageView(
        name=page.name,
        display_name=page.display_name,
        status=status,
        ordinal=page.ordinal,
        width=page.width,
        height=page.height,
        visuals=tuple(
            VisualView(
                name=v.name,
                visual_type=v.visual_type,
                title=v.title,
                status=status,
                old_position=v.position if is_old else None,
                new_position=None if is_old else v.position,
            )
            for v in sorted(page.visuals, key=lambda v: v.name)
        ),
    )


def _status_if_changed(path: str, paths: set[str]) -> ItemStatus:
    """Modified if any finding is about ``path`` or something inside it."""
    prefix = f"{path}/"
    changed = path in paths or any(p.startswith(prefix) for p in paths)
    return ItemStatus.MODIFIED if changed else ItemStatus.UNCHANGED
