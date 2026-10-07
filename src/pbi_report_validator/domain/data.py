"""Data validation: DAX queries, query results and data summaries."""

from enum import StrEnum

from pydantic import Field

from pbi_report_validator.domain.base import DomainModel

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


class DataStatus(StrEnum):
    """Outcome of comparing the data of one visual."""

    SAME = "same"
    DIFFERENT = "different"
    NOT_VALIDATED = "not_validated"


class DataSummary(DomainModel):
    """Data comparison result for one visual (``page/visual``).

    ``max_abs_delta`` is the largest numeric difference among matched rows,
    including differences within the tolerance (so small drift is visible).
    """

    path: str
    status: DataStatus
    rows_old: int = Field(default=0, ge=0)
    rows_new: int = Field(default=0, ge=0)
    rows_matched: int = Field(default=0, ge=0)
    rows_differing: int = Field(default=0, ge=0)
    rows_only_old: int = Field(default=0, ge=0)
    rows_only_new: int = Field(default=0, ge=0)
    max_abs_delta: float | None = None
    reason: str | None = None


class Tolerance(DomainModel):
    """How far two numbers may differ and still count as equal.

    Two numbers are equal when their difference is at most ``absolute`` or
    at most ``relative`` times the larger magnitude. Text is compared
    exactly.
    """

    absolute: float = Field(default=0.0, ge=0)
    relative: float = Field(default=1e-9, ge=0)
