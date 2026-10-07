"""Structural diff: compare matched report versions and produce findings.

Pure functions only. Paths in findings are ``<page>`` for pages and
``<page>/<visual>`` for visuals, using PBIR names (ids), which are stable
between versions; messages use display names where they help a reader.
"""

from collections.abc import Sequence

from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    Finding,
    MatchMethod,
    Page,
    PageMatch,
    ParseIssue,
    Position,
    ReportMatch,
    Visual,
    VisualMatch,
)


def diff_pages_and_visuals(match: ReportMatch) -> list[Finding]:
    """Compare pages and visuals of two matched report versions.

    Reports added, removed, renamed and reordered pages, and added,
    removed, moved, resized, retyped, retitled and re-identified visuals.
    Visuals on an added or removed page are covered by the page finding.
    """
    findings = [_page_added(p) for p in match.added_pages]
    findings += [_page_removed(p) for p in match.removed_pages]
    findings += _reordered_pages(match.pages)
    for page_match in match.pages:
        findings += _page_changes(page_match)
    return findings


def without_unparseable_visuals(
    findings: Sequence[Finding],
    old_issues: Sequence[ParseIssue],
    new_issues: Sequence[ParseIssue],
) -> list[Finding]:
    """Drop "added"/"removed" for visuals that exist but failed to parse.

    A visual that cannot be parsed in one version is missing from that
    version's model, which would otherwise read as added or removed. Its
    parse issue finding already reports the real problem.
    """
    broken_in_old = {i.visual for i in old_issues if i.visual}
    broken_in_new = {i.visual for i in new_issues if i.visual}
    return [
        f
        for f in findings
        if not (
            f.category == Category.VISUAL
            and (
                (f.change == ChangeKind.REMOVED and f.path in broken_in_new)
                or (f.change == ChangeKind.ADDED and f.path in broken_in_old)
            )
        )
    ]


def _page_added(page: Page) -> Finding:
    return Finding(
        category=Category.PAGE,
        change=ChangeKind.ADDED,
        path=page.name,
        message=f"Page '{page.display_name}' added with {_count(page)}",
        new=page.display_name,
    )


def _page_removed(page: Page) -> Finding:
    return Finding(
        category=Category.PAGE,
        change=ChangeKind.REMOVED,
        path=page.name,
        message=f"Page '{page.display_name}' removed with {_count(page)}",
        old=page.display_name,
    )


def _reordered_pages(pages: tuple[PageMatch, ...]) -> list[Finding]:
    """Pages whose position among the matched pages changed.

    Comparing ranks among matched pages only means that adding or removing
    a page does not mark every later page as moved.
    """
    old_rank = {
        m.old.name: i for i, m in enumerate(sorted(pages, key=lambda m: m.old.ordinal))
    }
    new_rank = {
        m.old.name: i for i, m in enumerate(sorted(pages, key=lambda m: m.new.ordinal))
    }
    return [
        Finding(
            category=Category.PAGE,
            change=ChangeKind.REORDERED,
            path=m.old.name,
            message=f"Page '{m.new.display_name}' moved from position "
            f"{old_rank[m.old.name] + 1} to {new_rank[m.old.name] + 1}",
            old=str(old_rank[m.old.name] + 1),
            new=str(new_rank[m.old.name] + 1),
        )
        for m in pages
        if old_rank[m.old.name] != new_rank[m.old.name]
    ]


def _page_changes(match: PageMatch) -> list[Finding]:
    findings = []
    if match.old.display_name != match.new.display_name:
        findings.append(
            Finding(
                category=Category.PAGE,
                change=ChangeKind.RENAMED,
                path=match.old.name,
                message=f"Page renamed from '{match.old.display_name}' "
                f"to '{match.new.display_name}'",
                old=match.old.display_name,
                new=match.new.display_name,
            )
        )
    if match.old.name != match.new.name:
        findings.append(
            Finding(
                category=Category.PAGE,
                change=ChangeKind.RENAMED,
                path=match.old.name,
                message=f"Page '{match.new.display_name}' has a new id; "
                "matched by display name",
                old=match.old.name,
                new=match.new.name,
            )
        )
    page = match.old.name
    findings += [_visual_added(page, v) for v in match.added_visuals]
    findings += [_visual_removed(page, v) for v in match.removed_visuals]
    for visual_match in match.visuals:
        findings += _visual_changes(page, visual_match)
    return findings


def _visual_added(page: str, visual: Visual) -> Finding:
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.ADDED,
        path=f"{page}/{visual.name}",
        message=f"{_describe(visual)} added",
        new=visual.visual_type,
    )


def _visual_removed(page: str, visual: Visual) -> Finding:
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.REMOVED,
        path=f"{page}/{visual.name}",
        message=f"{_describe(visual)} removed",
        old=visual.visual_type,
    )


def _visual_changes(page: str, match: VisualMatch) -> list[Finding]:
    path = f"{page}/{match.old.name}"
    candidates = (
        _new_id(path, match),
        _retyped(path, match.old, match.new),
        _retitled(path, match.old, match.new),
        _moved(path, match.old, match.new),
    )
    return [finding for finding in candidates if finding is not None]


def _new_id(path: str, match: VisualMatch) -> Finding | None:
    if match.method != MatchMethod.SIMILARITY:
        return None
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.RENAMED,
        path=path,
        message=f"{_describe(match.new)} has a new id; matched by similarity "
        f"({match.score:.2f})",
        old=match.old.name,
        new=match.new.name,
    )


def _retyped(path: str, old: Visual, new: Visual) -> Finding | None:
    if old.visual_type == new.visual_type:
        return None
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.RETYPED,
        path=path,
        message=f"{_describe(old)} changed type to {new.visual_type}",
        old=old.visual_type,
        new=new.visual_type,
    )


def _retitled(path: str, old: Visual, new: Visual) -> Finding | None:
    if old.title == new.title:
        return None
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.MODIFIED,
        path=path,
        message=f"Title of {old.visual_type} '{old.name}' changed",
        old=old.title,
        new=new.title,
    )


def _moved(path: str, old: Visual, new: Visual) -> Finding | None:
    movement = _movement(old.position, new.position)
    if not movement:
        return None
    return Finding(
        category=Category.VISUAL,
        change=ChangeKind.MOVED,
        path=path,
        message=f"{_describe(new)} {movement}",
        old=_format_position(old.position),
        new=_format_position(new.position),
    )


def _movement(old: Position, new: Position) -> str:
    moved = (old.x, old.y) != (new.x, new.y)
    resized = (old.width, old.height) != (new.width, new.height)
    if moved and resized:
        return "moved and resized"
    if moved:
        return "moved"
    return "resized" if resized else ""


def _format_position(position: Position) -> str:
    return (
        f"x={position.x:g}, y={position.y:g}, "
        f"width={position.width:g}, height={position.height:g}"
    )


def _describe(visual: Visual) -> str:
    title = f" '{visual.title}'" if visual.title else ""
    return f"{visual.visual_type}{title} ({visual.name})"


def _count(page: Page) -> str:
    count = len(page.visuals)
    return f"{count} visual" if count == 1 else f"{count} visuals"
