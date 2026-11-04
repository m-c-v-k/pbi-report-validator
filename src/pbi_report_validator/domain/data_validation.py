"""Data validation: DAX queries, query results and data summaries."""

from enum import StrEnum

from pydantic import Field

from pbi_report_validator.domain.base import DomainModel

CellValue = str | int | float | bool | None


class QueryResult(DomainModel):
    """The table returned by a DAX query, as returned by the Power BI API.

    ``columns`` keeps the column names in the order the API returned them
    (e.g. ``Date[Month]``, ``[Total Sales]``); each row has one value per
    column, ``None`` for blanks. ``response_bytes`` is the size of the API
    response the result came from (0 when unknown), used to spot results the
    API cut off at its size limit without saying so.
    """

    columns: tuple[str, ...] = ()
    rows: tuple[tuple[CellValue, ...], ...] = ()
    response_bytes: int = Field(default=0, ge=0)


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


class Attribution(StrEnum):
    """Where a data difference comes from (``--attribute``).

    Found by running the new report's query against the old dataset too:
    ``report`` if that already differs from the old version and matches
    the new one, ``model`` the other way round, ``both`` if it differs from
    each, and ``unknown`` if it could not be told (``attribution_reason``).
    """

    REPORT = "report"
    MODEL = "model"
    BOTH = "both"
    UNKNOWN = "unknown"


class DataSummary(DomainModel):
    """Data comparison result for one visual (``page/visual``).

    ``max_abs_delta`` is the largest numeric difference among matched rows,
    including differences within the tolerance (so small drift is visible).
    ``attribution`` is set only with ``--attribute``, on ``different``
    visuals.
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
    attribution: Attribution | None = None
    attribution_reason: str | None = None


class Tolerance(DomainModel):
    """How far two numbers may differ and still count as equal.

    Two numbers are equal when their difference is at most ``absolute`` or
    at most ``relative`` times the larger magnitude. Text is compared
    exactly.
    """

    absolute: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    relative: float = Field(default=1e-9, ge=0, allow_inf_nan=False)


class DataSettings(DomainModel):
    """What ``--data`` compares against.

    ``show_values`` puts row keys and values in the findings; by default
    they are masked. ``attribute`` runs one more query per differing visual
    to tell report changes from model changes.
    """

    old_dataset: str
    new_dataset: str
    tolerance: Tolerance = Tolerance()
    show_values: bool = False
    attribute: bool = False


class ValuePairing(DomainModel):
    """Value columns to compare, and the values found in one version only.

    ``columns`` holds ``(old column, new column)`` pairs, following measure
    renames.
    """

    columns: tuple[tuple[str, str], ...] = ()
    only_old: tuple[str, ...] = ()
    only_new: tuple[str, ...] = ()
