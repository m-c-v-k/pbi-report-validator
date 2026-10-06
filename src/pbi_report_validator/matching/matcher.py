"""Pair old and new pages and visuals deterministically.

Pages are matched by name, then by display name. Visuals on a matched page
are matched by name (their PBIR id), then by a similarity score over type,
title, fields and position. No AI is involved; the same input always gives
the same pairing.
"""

import math
from collections.abc import Callable, Sequence

from pbi_report_validator.domain.models import (
    MatchMethod,
    Page,
    PageMatch,
    ReportMatch,
    Visual,
    VisualMatch,
)

DEFAULT_THRESHOLD = 0.6
TYPE_WEIGHT = 0.3
FIELDS_WEIGHT = 0.3
TITLE_WEIGHT = 0.2
POSITION_WEIGHT = 0.2


def match_reports(
    old_pages: Sequence[Page],
    new_pages: Sequence[Page],
    threshold: float = DEFAULT_THRESHOLD,
) -> ReportMatch:
    """Match the pages of two report versions and the visuals on each page.

    Args:
        old_pages: Pages of the old report.
        new_pages: Pages of the new report.
        threshold: Minimum similarity (0-1) for pairing visuals whose ids
            differ.

    Returns:
        Matched pages (ordered by the old page order) and the pages only in
        the old or only in the new version.
    """
    by_name, old_left, new_left = _match_by_key(old_pages, new_pages, lambda p: p.name)
    by_display, old_left, new_left = _match_by_key(
        old_left, new_left, lambda p: p.display_name
    )
    pairs = [(o, n, MatchMethod.ID) for o, n in by_name]
    pairs += [(o, n, MatchMethod.DISPLAY_NAME) for o, n in by_display]
    pairs.sort(key=lambda pair: pair[0].ordinal)
    return ReportMatch(
        pages=tuple(_match_page(o, n, method, threshold) for o, n, method in pairs),
        removed_pages=tuple(sorted(old_left, key=lambda p: p.ordinal)),
        added_pages=tuple(sorted(new_left, key=lambda p: p.ordinal)),
    )


def match_visuals(
    old: Page, new: Page, threshold: float = DEFAULT_THRESHOLD
) -> tuple[list[VisualMatch], list[Visual], list[Visual]]:
    """Match the visuals of two versions of a page.

    Returns:
        Matched visuals, visuals only on the old page and visuals only on
        the new page, each sorted by visual name.
    """
    by_id, old_left, new_left = _match_by_key(
        old.visuals, new.visuals, lambda v: v.name
    )
    matches = [
        VisualMatch(old=o, new=n, method=MatchMethod.ID, score=1.0) for o, n in by_id
    ]
    candidates = sorted(
        (
            (score, o.name, n.name, o, n)
            for o in old_left
            for n in new_left
            if (score := similarity(o, n, old, new)) >= threshold
        ),
        key=lambda c: (-c[0], c[1], c[2]),
    )
    used_old: set[str] = set()
    used_new: set[str] = set()
    for score, old_name, new_name, o, n in candidates:
        if old_name in used_old or new_name in used_new:
            continue
        used_old.add(old_name)
        used_new.add(new_name)
        matches.append(
            VisualMatch(old=o, new=n, method=MatchMethod.SIMILARITY, score=score)
        )
    removed = [v for v in old_left if v.name not in used_old]
    added = [v for v in new_left if v.name not in used_new]
    return (
        sorted(matches, key=lambda m: m.old.name),
        sorted(removed, key=lambda v: v.name),
        sorted(added, key=lambda v: v.name),
    )


def similarity(old: Visual, new: Visual, old_page: Page, new_page: Page) -> float:
    """Score (0-1) how likely two visuals are the same visual."""
    score = TYPE_WEIGHT * (old.visual_type == new.visual_type)
    score += TITLE_WEIGHT * (old.title == new.title)
    score += FIELDS_WEIGHT * _jaccard(_field_keys(old), _field_keys(new))
    score += POSITION_WEIGHT * _position_closeness(old, new, old_page, new_page)
    return round(score, 6)


def _match_page(
    old: Page, new: Page, method: MatchMethod, threshold: float
) -> PageMatch:
    visuals, removed, added = match_visuals(old, new, threshold)
    return PageMatch(
        old=old,
        new=new,
        method=method,
        visuals=tuple(visuals),
        removed_visuals=tuple(removed),
        added_visuals=tuple(added),
    )


def _match_by_key[T: (Page, Visual)](
    old: Sequence[T], new: Sequence[T], key: Callable[[T], str]
) -> tuple[list[tuple[T, T]], list[T], list[T]]:
    """Pair items whose key is equal and unique on both sides."""
    old_by_key = _unique_by_key(old, key)
    new_by_key = _unique_by_key(new, key)
    shared = old_by_key.keys() & new_by_key.keys()
    pairs = [(old_by_key[k], new_by_key[k]) for k in sorted(shared)]
    old_left = [item for item in old if key(item) not in shared]
    new_left = [item for item in new if key(item) not in shared]
    return pairs, old_left, new_left


def _unique_by_key[T: (Page, Visual)](
    items: Sequence[T], key: Callable[[T], str]
) -> dict[str, T]:
    counts: dict[str, int] = {}
    for item in items:
        counts[key(item)] = counts.get(key(item), 0) + 1
    return {key(item): item for item in items if counts[key(item)] == 1}


def _field_keys(visual: Visual) -> set[str]:
    return {p.field.key for p in visual.projections}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _position_closeness(
    old: Visual, new: Visual, old_page: Page, new_page: Page
) -> float:
    """1 when the visual centres coincide, 0 when a page diagonal apart."""
    old_x, old_y = _centre(old, old_page)
    new_x, new_y = _centre(new, new_page)
    distance = math.hypot(old_x - new_x, old_y - new_y)
    return max(0.0, 1.0 - distance / math.sqrt(2))


def _centre(visual: Visual, page: Page) -> tuple[float, float]:
    """Centre of the visual as a fraction of the page size."""
    p = visual.position
    return (p.x + p.width / 2) / page.width, (p.y + p.height / 2) / page.height
