"""Matching, findings, page views and the diff result (the JSON root)."""

from collections import Counter
from enum import StrEnum
from typing import Final, Literal

from pydantic import Field, ValidationInfo, field_validator

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.data import DataSummary
from pbi_report_validator.domain.report import (
    Page,
    Position,
    Visual,
)

SCHEMA_VERSION: Final = "1.3"


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
    DATA = "data"


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


class Severity(StrEnum):
    """How much a finding matters, from least to most."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Finding(DomainModel):
    """One difference (or parse problem) between the old and new report.

    ``path`` locates the object, e.g. ``details/table_product_sales/filters/
    visual_filter_category`` or ``model/Sales/Total Sales``. ``severity`` is
    set by ``diff.severity``; findings are created with the lowest level.
    """

    category: Category
    change: ChangeKind
    severity: Severity = Severity.INFO
    path: str
    message: str
    old: str | None = None
    new: str | None = None
    # The ``page/visual`` a parse issue belongs to. Used to show the issue on
    # its visual in the HTML report; not part of the JSON output (schema
    # unchanged), since it is already implied by ``path``.
    visual: str | None = Field(default=None, exclude=True)

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


class DataComparison(DomainModel):
    """Summary and findings from comparing one visual's data."""

    summary: DataSummary
    findings: tuple[Finding, ...] = ()


class SeverityCounts(DomainModel):
    """Number of findings per severity."""

    critical: int = Field(default=0, ge=0)
    warning: int = Field(default=0, ge=0)
    info: int = Field(default=0, ge=0)


class DiffResult(DomainModel):
    """The result of comparing two report versions; the JSON output root.

    Schema history: 1.0 had sources and findings; 1.1 added ``pages``;
    1.2 added the ``data`` category and per-visual ``data`` summaries;
    1.3 added ``severity`` on findings and ``severity_counts``.
    """

    # Keep the Literal in sync with SCHEMA_VERSION (enforced by a test).
    schema_version: Literal["1.3"] = SCHEMA_VERSION
    old_source: str
    new_source: str
    findings: tuple[Finding, ...] = ()
    # Always derived from ``findings``; any value passed in is replaced. Must
    # stay declared after ``findings``: validators only see earlier fields.
    severity_counts: SeverityCounts = Field(
        default_factory=SeverityCounts, validate_default=True
    )
    pages: tuple[PageView, ...] = ()
    data: tuple[DataSummary, ...] = ()

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, findings: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(sorted(findings, key=lambda f: f.sort_key))

    @field_validator("severity_counts")
    @classmethod
    def _count_severities(
        cls, _: SeverityCounts, info: ValidationInfo
    ) -> SeverityCounts:
        findings: tuple[Finding, ...] = info.data.get("findings", ())
        counts = Counter(f.severity for f in findings)
        return SeverityCounts(**{s.value: counts[s] for s in Severity})
