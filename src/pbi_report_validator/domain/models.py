"""Domain models for reports, semantic models and diff results.

All models are immutable Pydantic models. Collections are tuples so that a
model can be hashed, compared and serialised deterministically.
"""

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Final = "1.0"


class DomainModel(BaseModel):
    """Base class: frozen, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# --- Report side -------------------------------------------------------------


class FieldKind(StrEnum):
    """What a field reference points to in the semantic model."""

    COLUMN = "column"
    MEASURE = "measure"
    AGGREGATION = "aggregation"
    HIERARCHY_LEVEL = "hierarchy_level"
    UNKNOWN = "unknown"


class FieldRef(DomainModel):
    """A reference from a visual or filter to a model column or measure."""

    table: str
    name: str
    kind: FieldKind
    aggregation: str | None = None

    @property
    def key(self) -> str:
        """DAX-style identifier, e.g. ``Sales[Total Sales]``."""
        return f"{self.table}[{self.name}]"


class Projection(DomainModel):
    """A field placed in a visual role (e.g. ``Category``, ``Y``, ``Values``)."""

    role: str
    field: FieldRef


class FilterLevel(StrEnum):
    """Where a filter is defined."""

    REPORT = "report"
    PAGE = "page"
    VISUAL = "visual"


class Filter(DomainModel):
    """A filter card on the report, a page or a visual.

    ``condition`` is a normalised, human-readable form of the filter
    expression (for example ``Product[Category] in ('Bikes', 'Clothing')``),
    or ``None`` when the filter card has no active condition.
    """

    name: str
    level: FilterLevel
    field: FieldRef | None
    filter_type: str
    condition: str | None = None


class SlicerState(DomainModel):
    """The selection of a slicer visual, normalised like a filter condition."""

    field: FieldRef | None
    condition: str | None = None


class Position(DomainModel):
    """Position and size of a visual on its page, in report pixels."""

    x: float = Field(ge=0)
    y: float = Field(ge=0)
    z: int = Field(default=0, ge=0)
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class Visual(DomainModel):
    """A visual on a page."""

    name: str
    visual_type: str
    position: Position
    title: str | None = None
    projections: tuple[Projection, ...] = ()
    filters: tuple[Filter, ...] = ()
    slicer: SlicerState | None = None


class Page(DomainModel):
    """A report page with its visuals, in display order."""

    name: str
    display_name: str
    ordinal: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    filters: tuple[Filter, ...] = ()
    visuals: tuple[Visual, ...] = ()


class ParseIssue(DomainModel):
    """Something in the input that could not be parsed.

    Parse issues are reported as findings instead of aborting the run.
    """

    path: str
    message: str


class Report(DomainModel):
    """A parsed report definition."""

    filters: tuple[Filter, ...] = ()
    pages: tuple[Page, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


# --- Semantic model side -----------------------------------------------------


class Column(DomainModel):
    """A column in a semantic model table."""

    name: str
    data_type: str | None = None


class Measure(DomainModel):
    """A DAX measure with its full expression."""

    name: str
    expression: str


class Table(DomainModel):
    """A semantic model table."""

    name: str
    columns: tuple[Column, ...] = ()
    measures: tuple[Measure, ...] = ()


class SemanticModel(DomainModel):
    """A parsed semantic model (TMDL)."""

    tables: tuple[Table, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


# --- Diff side ---------------------------------------------------------------


class Category(StrEnum):
    """What kind of object a finding is about."""

    PAGE = "page"
    VISUAL = "visual"
    FIELD = "field"
    FILTER = "filter"
    SLICER = "slicer"
    MEASURE = "measure"
    PARSE_ISSUE = "parse_issue"


class ChangeKind(StrEnum):
    """How the object changed between the old and new version."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    MOVED = "moved"
    RETYPED = "retyped"
    RENAMED = "renamed"
    REORDERED = "reordered"
    ERROR = "error"


class Finding(DomainModel):
    """One difference (or parse problem) between the old and new report.

    ``path`` locates the object, e.g. ``details/table_product_sales/filters/
    visual_filter_category`` or ``model/Sales/Total Sales``.
    """

    category: Category
    change: ChangeKind
    path: str
    message: str
    old: str | None = None
    new: str | None = None

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Key giving a stable, readable order of findings."""
        return (self.path, self.category.value, self.change.value)


class DiffResult(DomainModel):
    """The result of comparing two report versions; the JSON output root."""

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    old_source: str
    new_source: str
    findings: tuple[Finding, ...] = ()

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(sorted(findings, key=lambda f: f.sort_key))
