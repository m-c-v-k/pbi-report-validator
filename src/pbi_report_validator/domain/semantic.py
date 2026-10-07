"""Semantic model side: tables, columns and measures."""

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.report import ParseIssue


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
