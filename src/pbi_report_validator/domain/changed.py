"""The projects a git-aware run (``pbi-validate changed``) looked at."""

from collections import Counter
from enum import StrEnum
from typing import Literal

from pydantic import Field, TypeAdapter, field_validator, model_validator

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.diff import (
    SCHEMA_VERSION,
    DiffResult,
    Severity,
    SeverityCounts,
)


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


_PROJECTS: TypeAdapter[tuple[ProjectRun, ...]] = TypeAdapter(tuple[ProjectRun, ...])


class ChangedResult(DomainModel):
    """The result of ``pbi-validate changed``; its JSON output root.

    Shares ``schema_version`` with ``DiffResult``: 1.12 added this root.
    Projects are ordered by path. ``severity_counts`` totals the findings of
    every compared project; added and removed projects are not findings.
    """

    # Keep the Literal in sync with SCHEMA_VERSION (enforced by a test).
    schema_version: Literal["1.12"] = SCHEMA_VERSION
    base: str
    # Always derived from ``projects``; any value passed in is replaced.
    severity_counts: SeverityCounts = Field(default_factory=SeverityCounts)
    projects: tuple[ProjectRun, ...] = ()

    @field_validator("projects")
    @classmethod
    def _sort_projects(cls, projects: tuple[ProjectRun, ...]) -> tuple[ProjectRun, ...]:
        return tuple(sorted(projects, key=lambda run: run.path))

    @model_validator(mode="before")
    @classmethod
    def _count_severities(cls, data: object) -> object:
        """Replace ``severity_counts`` with the totals over ``projects``."""
        if not isinstance(data, dict):
            return data
        counts: Counter[Severity] = Counter()
        for run in _PROJECTS.validate_python(data.get("projects", ())):
            if run.result is not None:
                counts.update(f.severity for f in run.result.findings)
        severity_counts = SeverityCounts(**{s.value: counts[s] for s in Severity})
        return {**data, "severity_counts": severity_counts}
