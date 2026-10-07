"""Report side: pages, visuals, fields, filters and their conditions."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from pbi_report_validator.domain.base import DomainModel


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
    ``visual`` is the ``page/visual`` the issue belongs to, if any;
    ``page`` is set when the whole page could not be parsed.
    """

    path: str
    message: str
    visual: str | None = None
    page: str | None = None


class Report(DomainModel):
    """A parsed report definition."""

    filters: tuple[Filter, ...] = ()
    pages: tuple[Page, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


# Resolve the forward references of the recursive condition models.
NotCondition.model_rebuild()
BinaryCondition.model_rebuild()
AllCondition.model_rebuild()
Filter.model_rebuild()
SlicerState.model_rebuild()
