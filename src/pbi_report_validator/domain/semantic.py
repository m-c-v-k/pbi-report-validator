"""Semantic model side: tables, columns and measures."""

from collections.abc import Mapping

from pbi_report_validator.domain.base import DomainModel, Located
from pbi_report_validator.domain.helpers import field_key
from pbi_report_validator.domain.report import ParseIssue


class Column(DomainModel):
    """A column in a semantic model table."""

    name: str
    data_type: str | None = None


class Measure(Located):
    """A DAX measure with its full expression."""

    name: str
    expression: str


class Table(DomainModel):
    """A semantic model table."""

    name: str
    columns: tuple[Column, ...] = ()
    measures: tuple[Measure, ...] = ()


class SemanticModel(DomainModel):
    """A parsed semantic model (TMDL or TMSL ``model.bim``)."""

    tables: tuple[Table, ...] = ()
    issues: tuple[ParseIssue, ...] = ()


class MeasureRename(DomainModel):
    """A measure renamed in its table or moved to another table.

    Table and name are kept apart: ``Table[Name]`` keys do not escape
    brackets, so a key cannot be split back reliably.
    """

    old_table: str
    old_name: str
    new_table: str
    new_name: str

    @property
    def new_key(self) -> str:
        """The new ``Table[Name]`` key."""
        return field_key(self.new_table, self.new_name)


def renamed_key(key: str, renames: Mapping[str, MeasureRename]) -> str:
    """``key`` after a measure rename (renames are keyed by old key)."""
    rename = renames.get(key)
    return rename.new_key if rename else key
