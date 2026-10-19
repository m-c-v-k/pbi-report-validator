"""Data validation: run each visual's query against both datasets and compare.

Opt-in (``--data``). For every visual present in both versions the old and
new DAX queries are built, run one after the other (to stay within the API
rate limits) and their results compared. Query results stay in memory and
are never sent anywhere else.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from pbi_report_validator.dax.builder import build_query, result_column
from pbi_report_validator.diff.data import compare_results, not_validated
from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.helpers import field_name, visual_path
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataComparison,
    DaxQuery,
    DomainModel,
    QueryResult,
    Report,
    ReportMatch,
    Tolerance,
    UnsupportedQuery,
)
from pbi_report_validator.integrations.config import load_powerbi_config
from pbi_report_validator.integrations.powerbi import (
    QueryError,
    RateLimitError,
    ServiceError,
    create_client,
)

logger = logging.getLogger(__name__)


class QueryRunner(Protocol):
    """Runs a DAX query against a dataset (the Power BI client in production)."""

    def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
        """Return the first result table of ``dax`` on ``dataset_id``."""
        ...


class InvalidDataOptionsError(ValueError):
    """The data validation options are incomplete or inconsistent."""


class DataSettings(DomainModel):
    """What ``--data`` compares against.

    ``show_values`` puts row keys and values in the findings; by default
    they are masked.
    """

    old_dataset: str
    new_dataset: str
    tolerance: Tolerance = Tolerance()
    show_values: bool = False


@dataclass(frozen=True)
class DataRun:
    """Data validation settings plus the runner that executes the queries."""

    settings: DataSettings
    runner: QueryRunner


def data_settings(
    old_dataset: str | None,
    new_dataset: str | None,
    absolute: float = 0.0,
    relative: float = 1e-9,
    show_values: bool = False,
) -> DataSettings:
    """Settings from the CLI options.

    Raises:
        InvalidDataOptionsError: A dataset id is missing.
    """
    if not old_dataset or not new_dataset:
        raise InvalidDataOptionsError("--data needs --old-dataset and --new-dataset")
    return DataSettings(
        old_dataset=old_dataset,
        new_dataset=new_dataset,
        tolerance=Tolerance(absolute=absolute, relative=relative),
        show_values=show_values,
    )


def create_runner(environ: Mapping[str, str]) -> QueryRunner:
    """A Power BI client from ``PBI_*`` environment variables.

    Raises:
        MissingCredentialsError: A variable is missing.
        AuthenticationError: The tenant is unknown or invalid.
        ServiceError: Entra ID could not be reached.
    """
    return create_client(load_powerbi_config(environ))


def validate_data(
    old: Report,
    new: Report,
    match: ReportMatch,
    renames: Mapping[str, str],
    runner: QueryRunner,
    settings: DataSettings,
) -> list[DataComparison]:
    """Compare the data of every matched visual.

    Slicers are skipped (they show no numbers of their own). A visual whose
    query cannot be built or fails becomes a ``not_validated`` result.

    Raises:
        AuthenticationError: The service principal cannot sign in.
        DatasetNotFoundError: A dataset id is wrong or not shared.
        InvalidDatasetIdError: A dataset id is not a GUID.
    """
    value_renames = _value_renames(renames)
    comparisons = []
    for page_match in match.pages:
        for visual_match in page_match.visuals:
            if visual_match.old.slicer or visual_match.new.slicer:
                continue
            path = visual_path(page_match.old.name, visual_match.old.name)
            old_query = build_query(visual_match.old, page_match.old, old.filters)
            new_query = build_query(visual_match.new, page_match.new, new.filters)
            comparisons.append(
                _compare(path, old_query, new_query, value_renames, runner, settings)
            )
    logger.info("Compared the data of %d visuals", len(comparisons))
    return comparisons


def _compare(
    path: str,
    old_query: DaxQuery | UnsupportedQuery,
    new_query: DaxQuery | UnsupportedQuery,
    value_renames: Mapping[str, str],
    runner: QueryRunner,
    settings: DataSettings,
) -> DataComparison:
    queries = _comparable_queries(old_query, new_query)
    if isinstance(queries, str):
        return not_validated(path, queries)
    old_dax, new_dax = queries
    try:
        old_result = runner.execute_query(settings.old_dataset, old_dax.dax)
        new_result = runner.execute_query(settings.new_dataset, new_dax.dax)
    except (QueryError, RateLimitError, ServiceError) as exc:
        return not_validated(path, f"query failed: {exc}")
    keys = [(result_column(c), result_column(c)) for c in old_dax.group_by]
    values = _pair_values(old_dax.values, new_dax.values, value_renames)
    comparison = compare_results(
        path,
        old_result,
        new_result,
        keys,
        values.columns,
        settings.tolerance,
        show_values=settings.show_values,
    )
    return _with_unpaired(comparison, path, values.only_old, values.only_new)


def _comparable_queries(
    old: DaxQuery | UnsupportedQuery, new: DaxQuery | UnsupportedQuery
) -> tuple[DaxQuery, DaxQuery] | str:
    """Both queries if their results can be compared, otherwise the reason."""
    if isinstance(old, UnsupportedQuery):
        return old.reason
    if isinstance(new, UnsupportedQuery):
        return new.reason
    old_columns = [result_column(c) for c in old.group_by]
    if old_columns != [result_column(c) for c in new.group_by]:
        return "the visual is grouped by different columns"
    return old, new


@dataclass(frozen=True)
class _ValuePairs:
    """Value columns to compare, and the values found in one version only."""

    columns: list[tuple[str, str]]
    only_old: list[str]
    only_new: list[str]


def _pair_values(
    old: Sequence[str], new: Sequence[str], value_renames: Mapping[str, str]
) -> _ValuePairs:
    """Pair old and new value names, following measure renames."""
    renamed = {name: value_renames.get(name, name) for name in old}
    return _ValuePairs(
        columns=[(f"[{o}]", f"[{n}]") for o, n in renamed.items() if n in new],
        only_old=[o for o, n in renamed.items() if n not in new],
        only_new=[n for n in new if n not in renamed.values()],
    )


def _with_unpaired(
    comparison: DataComparison, path: str, only_old: list[str], only_new: list[str]
) -> DataComparison:
    """Note values that exist in only one version, so they are not hidden."""
    parts = [f"[{n}] is only in the old visual" for n in only_old]
    parts += [f"[{n}] is only in the new visual" for n in only_new]
    if not parts:
        return comparison
    note = "not compared: " + "; ".join(parts)
    finding = make_finding(
        Category.DATA,
        ChangeKind.ERROR,
        path=f"{path}/data",
        message=f"Data partly validated, {note}",
    )
    summary = comparison.summary.model_copy(update={"reason": note})
    return DataComparison(summary=summary, findings=(*comparison.findings, finding))


def _value_renames(renames: Mapping[str, str]) -> dict[str, str]:
    """Measure renames by name: ``Sales[Margin %]`` -> ``Margin %``."""
    return {field_name(old): field_name(new) for old, new in renames.items()}
