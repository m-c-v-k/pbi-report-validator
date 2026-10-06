"""Data validation: run each visual's query against both datasets and compare.

Opt-in (``--data``). For every visual present in both versions the old and
new DAX queries are built, run one after the other (to stay within the API
rate limits) and their results compared. Query results stay in memory and
are never sent anywhere else.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from pbi_report_validator.dax.builder import build_query
from pbi_report_validator.diff.data import compare_results, not_validated
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataComparison,
    DaxQuery,
    DomainModel,
    Finding,
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
    """What ``--data`` compares against."""

    old_dataset: str
    new_dataset: str
    tolerance: Tolerance = Tolerance()


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
    )


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
    paired = {name: names.get(name, name) for name in old_query.values}
    values = [
        (f"[{old}]", f"[{new}]")
        for old, new in paired.items()
        if new in new_query.values
    ]
    comparison = compare_results(
        path, old_result, new_result, keys, values, settings.tolerance
    )
    only_old = [old for old, new in paired.items() if new not in new_query.values]
    only_new = [n for n in new_query.values if n not in paired.values()]
    return _with_unpaired(comparison, path, only_old, only_new)


def _with_unpaired(
    comparison: DataComparison, path: str, only_old: list[str], only_new: list[str]
) -> DataComparison:
    """Note values that exist in only one version, so they are not hidden."""
    parts = [f"[{n}] is only in the old visual" for n in only_old]
    parts += [f"[{n}] is only in the new visual" for n in only_new]
    if not parts:
        return comparison
    note = "not compared: " + "; ".join(parts)
    finding = Finding(
        category=Category.DATA,
        change=ChangeKind.ERROR,
        path=f"{path}/data",
        message=f"Data partly validated, {note}",
    )
    summary = comparison.summary.model_copy(update={"reason": note})
    return DataComparison(summary=summary, findings=(*comparison.findings, finding))


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
