"""Domain models for reports, semantic models and diff results.

All models are immutable Pydantic models. Collections are tuples so that a
model can be hashed, compared and serialised deterministically.
"""

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION: Final = "1.1"


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


class LiteralKind(StrEnum):
    """Type of a literal value in a filter condition."""

    NUMBER = "number"
    TEXT = "text"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    NULL = "null"
    OTHER = "other"


class LiteralValue(DomainModel):
    """A literal in a filter condition.

    ``value`` is normalised: numbers without type suffix, text unquoted,
    datetimes as ISO text, booleans as ``true``/``false``, ``""`` for null.
    ``OTHER`` keeps the raw PBIR literal.
    """

    kind: LiteralKind
    value: str


class InCondition(DomainModel):
    """``field in (values)``; several fields compare tuples of values."""

    kind: Literal["in"] = "in"
    fields: tuple[FieldRef, ...]
    rows: tuple[tuple[LiteralValue, ...], ...]


class ComparisonCondition(DomainModel):
    """``field <operator> value`` with operator one of ``= > >= < <=``."""

    kind: Literal["comparison"] = "comparison"
    field: FieldRef
    operator: Literal["=", ">", ">=", "<", "<="]
    value: LiteralValue


class NotCondition(DomainModel):
    """Negation of another condition."""

    kind: Literal["not"] = "not"
    operand: "Condition"


class BinaryCondition(DomainModel):
    """``left and right`` or ``left or right``."""

    kind: Literal["and", "or"]
    left: "Condition"
    right: "Condition"


class AllCondition(DomainModel):
    """Several top-level conditions of one filter, all of which must hold."""

    kind: Literal["all"] = "all"
    items: tuple["Condition", ...]


Condition = Annotated[
    InCondition | ComparisonCondition | NotCondition | BinaryCondition | AllCondition,
    Field(discriminator="kind"),
]


class Filter(DomainModel):
    """A filter card on the report, a page or a visual.

    ``condition`` is a normalised, human-readable form of the filter
    expression (for example ``Product[Category] in ('Bikes', 'Clothing')``),
    or ``None`` when the filter card has no active condition. ``expression``
    is the same condition in structured form, used to build DAX.
    """

    name: str
    level: FilterLevel
    filter_type: str
    field: FieldRef | None = None
    condition: str | None = None
    expression: Condition | None = None


class SlicerState(DomainModel):
    """The selection of a slicer visual, normalised like a filter condition."""

    field: FieldRef | None = None
    condition: str | None = None
    expression: Condition | None = None


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


# --- Data validation ---------------------------------------------------------

CellValue = str | int | float | bool | None


class QueryResult(DomainModel):
    """The table returned by a DAX query, as returned by the Power BI API.

    ``columns`` keeps the column names in the order the API returned them
    (e.g. ``Date[Month]``, ``[Total Sales]``); each row has one value per
    column, ``None`` for blanks.
    """

    columns: tuple[str, ...] = ()
    rows: tuple[tuple[CellValue, ...], ...] = ()


class DaxQuery(DomainModel):
    """A DAX query that returns what a visual shows.

    ``group_by`` are the DAX column references the result is grouped by
    (the key for comparing rows); ``values`` the names of the computed
    columns, in order.
    """

    dax: str
    group_by: tuple[str, ...] = ()
    values: tuple[str, ...] = ()


class UnsupportedQuery(DomainModel):
    """Why no DAX query could be built for a visual."""

    reason: str


# --- Matching ----------------------------------------------------------------


class MatchMethod(StrEnum):
    """How an old object was paired with a new one."""

    ID = "id"
    DISPLAY_NAME = "display_name"
    SIMILARITY = "similarity"


class VisualMatch(DomainModel):
    """An old visual paired with its counterpart in the new version."""

    old: Visual
    new: Visual
    method: MatchMethod
    score: float = Field(ge=0, le=1)


class PageMatch(DomainModel):
    """An old page paired with a new page, with its visuals matched."""

    old: Page
    new: Page
    method: MatchMethod
    visuals: tuple[VisualMatch, ...] = ()
    removed_visuals: tuple[Visual, ...] = ()
    added_visuals: tuple[Visual, ...] = ()


class ReportMatch(DomainModel):
    """Pairing of all pages and visuals between two report versions."""

    pages: tuple[PageMatch, ...] = ()
    removed_pages: tuple[Page, ...] = ()
    added_pages: tuple[Page, ...] = ()


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
    def sort_key(self) -> tuple[str, str, str, str, str, str]:
        """Key giving a total, readable order of findings."""
        return (
            self.path,
            self.category.value,
            self.change.value,
            self.message,
            self.old or "",
            self.new or "",
        )


class ItemStatus(StrEnum):
    """Overall status of a page or visual in the comparison."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class VisualView(DomainModel):
    """A visual as shown in reports: both positions and a status.

    ``name`` is the old name for matched and removed visuals and the new
    name for added ones, so it matches the paths used in findings. For
    matched visuals, ``visual_type`` and ``title`` come from the new version.
    """

    name: str
    visual_type: str
    title: str | None = None
    status: ItemStatus
    old_position: Position | None = None
    new_position: Position | None = None


class PageView(DomainModel):
    """A page as shown in reports, with every visual of both versions."""

    name: str
    display_name: str
    status: ItemStatus
    ordinal: int = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    visuals: tuple[VisualView, ...] = ()


class DiffResult(DomainModel):
    """The result of comparing two report versions; the JSON output root.

    Schema history: 1.0 had sources and findings; 1.1 added ``pages``.
    """

    # Keep the Literal in sync with SCHEMA_VERSION (enforced by a test).
    schema_version: Literal["1.1"] = SCHEMA_VERSION
    old_source: str
    new_source: str
    findings: tuple[Finding, ...] = ()
    pages: tuple[PageView, ...] = ()

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(sorted(findings, key=lambda f: f.sort_key))


# Resolve the forward references of the recursive condition models.
NotCondition.model_rebuild()
BinaryCondition.model_rebuild()
AllCondition.model_rebuild()
Filter.model_rebuild()
SlicerState.model_rebuild()
