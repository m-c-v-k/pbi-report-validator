"""The projects a git-aware run (``pbi-validate changed``) looked at."""

from enum import StrEnum

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.diff import DiffResult


class ProjectStatus(StrEnum):
    """What happened to a project between the base ref and the working tree."""

    CHANGED = "changed"
    ADDED = "added"
    REMOVED = "removed"
    SKIPPED = "skipped"
    ERROR = "error"


class ProjectRun(DomainModel):
    """One changed report, ``.pbit`` or semantic model, and its comparison.

    ``path`` is relative to the repository root. ``result`` is set for a
    changed project that could be compared; ``message`` says why a project
    was skipped or could not be compared.
    """

    path: str
    status: ProjectStatus
    result: DiffResult | None = None
    message: str | None = None
