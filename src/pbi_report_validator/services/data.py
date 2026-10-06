"""Data validation: run each visual's query against both datasets and compare.

Opt-in (``--data``). For every visual present in both versions the old and
new DAX queries are built, run one after the other (to stay within the API
rate limits) and their results compared. Query results stay in memory and
are never sent anywhere else.
"""

import logging
from collections.abc import Mapping
from typing import Protocol

from pbi_report_validator.dax.builder import build_query
from pbi_report_validator.diff.data import compare_results, not_validated
from pbi_report_validator.domain.models import (
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


class DataSettings(DomainModel):
    """What ``--data`` compares against."""

    old_dataset: str
    new_dataset: str
    tolerance: Tolerance = Tolerance()


def create_runner(environ: Mapping[str, str]) -> QueryRunner:
    """A Power BI client from ``PBI_*`` environment variables.

    Raises:
        MissingCredentialsError: A variable is missing.
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
    names = _value_renames(renames)
    comparisons = []
    for page_match in match.pages:
        for visual_match in page_match.visuals:
            if visual_match.old.slicer or visual_match.new.slicer:
                continue
            path = f"{page_match.old.name}/{visual_match.old.name}"
            old_query = build_query(visual_match.old, page_match.old, old.filters)
            new_query = build_query(visual_match.new, page_match.new, new.filters)
            comparisons.append(
                _compare(path, old_query, new_query, names, runner, settings)
            )
    logger.info("Compared the data of %d visuals", len(comparisons))
    return comparisons


def _compare(
    path: str,
    old_query: DaxQuery | UnsupportedQuery,
    new_query: DaxQuery | UnsupportedQuery,
    names: Mapping[str, str],
    runner: QueryRunner,
    settings: DataSettings,
) -> DataComparison:
    if isinstance(old_query, UnsupportedQuery):
        return not_validated(path, old_query.reason)
    if isinstance(new_query, UnsupportedQuery):
        return not_validated(path, new_query.reason)
    if [result_column(c) for c in old_query.group_by] != [
        result_column(c) for c in new_query.group_by
    ]:
        return not_validated(path, "the visual is grouped by different columns")
    try:
        old_result = runner.execute_query(settings.old_dataset, old_query.dax)
        new_result = runner.execute_query(settings.new_dataset, new_query.dax)
    except (QueryError, RateLimitError, ServiceError) as exc:
        return not_validated(path, f"query failed: {exc}")
    keys = [(result_column(c), result_column(c)) for c in old_query.group_by]
    values = [
        (f"[{name}]", f"[{names.get(name, name)}]")
        for name in old_query.values
        if names.get(name, name) in new_query.values
    ]
    return compare_results(
        path, old_result, new_result, keys, values, settings.tolerance
    )


def result_column(reference: str) -> str:
    """The API's name for a group-by column: ``'Date'[Month]`` -> ``Date[Month]``."""
    table, _, column = reference.partition("[")
    name = table.removeprefix("'").removesuffix("'").replace("''", "'")
    return f"{name}[{column}"


def _value_renames(renames: Mapping[str, str]) -> dict[str, str]:
    """Measure renames by name: ``Sales[Margin %]`` -> ``Margin %``."""
    return {
        old.partition("[")[2].removesuffix("]"): new.partition("[")[2].removesuffix("]")
        for old, new in renames.items()
    }
