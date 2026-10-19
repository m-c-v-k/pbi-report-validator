"""Shared builders for test data: domain objects and the fixture reports.

Tests use these instead of defining their own ``visual()`` / ``page()``
helpers. Test files that need different defaults wrap them in one line.
"""

from collections.abc import Sequence
from pathlib import Path

from pbi_report_validator.domain.models import (
    Condition,
    FieldKind,
    FieldRef,
    Filter,
    FilterLevel,
    LiteralKind,
    LiteralValue,
    Page,
    Position,
    Projection,
    Report,
    SlicerState,
    Visual,
)
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.pbir import parse_report

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent
SNAPSHOTS = Path(__file__).parent / "snapshots"


def fixture_report(name: str) -> Report:
    """The parsed report of a fixture project, e.g. ``sales_v1``."""
    return parse_report(load_project(FIXTURES / name).report)


def fixture_pages(name: str) -> tuple[Page, ...]:
    """The pages of a fixture report."""
    return fixture_report(name).pages


def measure(name: str, table: str = "Sales") -> FieldRef:
    """A measure reference."""
    return FieldRef(table=table, name=name, kind=FieldKind.MEASURE)


def column(name: str, table: str = "Sales") -> FieldRef:
    """A column reference."""
    return FieldRef(table=table, name=name, kind=FieldKind.COLUMN)


def number(value: str) -> LiteralValue:
    """A number literal."""
    return LiteralValue(kind=LiteralKind.NUMBER, value=value)


def visual(
    name: str = "v",
    visual_type: str = "card",
    *,
    title: str | None = None,
    fields: Sequence[FieldRef] = (),
    role: str = "Values",
    projections: Sequence[Projection] = (),
    x: float = 0,
    y: float = 0,
    width: float = 100,
    height: float = 100,
    z: int = 0,
    filters: Sequence[Filter] = (),
    slicer: SlicerState | None = None,
) -> Visual:
    """A visual; ``fields`` become projections in ``role``."""
    return Visual(
        name=name,
        visual_type=visual_type,
        title=title,
        position=Position(x=x, y=y, z=z, width=width, height=height),
        projections=(
            *projections,
            *(Projection(role=role, field=f) for f in fields),
        ),
        filters=tuple(filters),
        slicer=slicer,
    )


def page(
    name: str = "p",
    *visuals: Visual,
    ordinal: int = 0,
    display: str | None = None,
    width: float = 1000,
    height: float = 1000,
    filters: Sequence[Filter] = (),
) -> Page:
    """A page; the display name defaults to the title-cased name."""
    return Page(
        name=name,
        display_name=display or name.title(),
        ordinal=ordinal,
        width=width,
        height=height,
        filters=tuple(filters),
        visuals=visuals,
    )


def report(*pages: Page, filters: Sequence[Filter] = ()) -> Report:
    """A report with report-level filters."""
    return Report(filters=tuple(filters), pages=pages)


def filter_card(
    expression: Condition | None = None,
    *,
    name: str = "f",
    condition: str | None = None,
    level: FilterLevel = FilterLevel.VISUAL,
    filter_type: str = "Categorical",
) -> Filter:
    """A filter card with a structured expression and/or condition text."""
    return Filter(
        name=name,
        level=level,
        filter_type=filter_type,
        condition=condition,
        expression=expression,
    )
