"""What the optional AI layer may send to the model."""

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.data_validation import DataStatus
from pbi_report_validator.domain.diff import Category, ChangeKind, Severity


class AiFinding(DomainModel):
    """A finding as sent to the model.

    Data findings carry no row keys or values unless data is allowed.
    """

    category: Category
    change: ChangeKind
    severity: Severity
    path: str
    message: str
    old: str | None = None
    new: str | None = None


class AiDataSummary(DomainModel):
    """Counts from comparing one visual's data, without values by default."""

    path: str
    status: DataStatus
    rows_old: int = 0
    rows_new: int = 0
    rows_matched: int = 0
    rows_differing: int = 0
    rows_only_old: int = 0
    rows_only_new: int = 0
    max_abs_delta: float | None = None
    reason: str | None = None


class AiPayload(DomainModel):
    """Everything about a diff that may be sent to the model.

    ``data_included`` is true only with ``--allow-data-to-llm``.
    """

    findings: tuple[AiFinding, ...] = ()
    data: tuple[AiDataSummary, ...] = ()
    data_included: bool = False
