"""Data validation: run each visual's query against both datasets and compare.

Opt-in (``--data``). For every visual present in both versions the old and
new DAX queries are built, run one after the other (to stay within the API
rate limits) and their results compared. Query results stay in memory and
are never sent anywhere else.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Protocol

from pydantic import ValidationError

from pbi_report_validator.dax.builder import build_query, result_column
from pbi_report_validator.diff.results import compare_results, not_validated
from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.helpers import field_name, visual_path
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataComparison,
    DataSettings,
    DaxQuery,
    QueryResult,
    Report,
    ReportMatch,
    Tolerance,
    UnsupportedQuery,
    ValuePairing,
)
from pbi_report_validator.integrations.config import load_powerbi_config
from pbi_report_validator.integrations.powerbi import (
    QueryError,
    RateLimitError,
    ServiceError,
    create_client,
)

logger = logging.getLogger(__name__)

ENGINE_MESSAGE_MASKED = (
    "the engine's message is masked (it can quote data values); "
    "rerun with --show-data-values to see it"
)


class QueryRunner(Protocol):
    """Runs a DAX query against a dataset (the Power BI client in production)."""

    def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
        """Return the first result table of ``dax`` on ``dataset_id``."""
        ...


class InvalidDataOptionsError(ValueError):
    """The data validation options are incomplete or inconsistent."""


def data_settings(
    old_dataset: str | None,
    new_dataset: str | None,
    absolute: float = 0.0,
    relative: float = 1e-9,
    show_values: bool = False,
) -> DataSettings:
    """Settings from the CLI options.

    Raises:
        InvalidDataOptionsError: A dataset id is missing, or a tolerance is
            negative or not a finite number.
    """
    if not old_dataset or not new_dataset:
        raise InvalidDataOptionsError("--data needs --old-dataset and --new-dataset")
    try:
        tolerance = Tolerance(absolute=absolute, relative=relative)
    except ValidationError as exc:
        raise InvalidDataOptionsError(
            "--abs-tol and --rel-tol must be finite numbers of at least 0"
        ) from exc
    return DataSettings(
        old_dataset=old_dataset,
        new_dataset=new_dataset,
        tolerance=tolerance,
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
        return not_validated(path, _failure_reason(exc, settings.show_values))
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


def _failure_reason(exc: Exception, show_values: bool) -> str:
    """Why a query failed; the engine's message may quote data values."""
    if isinstance(exc, QueryError) and not show_values:
        return f"query failed: {ENGINE_MESSAGE_MASKED}"
    return f"query failed: {exc}"


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


def _pair_values(
    old: Sequence[str], new: Sequence[str], value_renames: Mapping[str, str]
) -> ValuePairing:
    """Pair old and new value names, following measure renames."""
    renamed = {name: value_renames.get(name, name) for name in old}
    return ValuePairing(
        columns=tuple((f"[{o}]", f"[{n}]") for o, n in renamed.items() if n in new),
        only_old=tuple(o for o, n in renamed.items() if n not in new),
        only_new=tuple(n for n in new if n not in renamed.values()),
    )


def _with_unpaired(
    comparison: DataComparison,
    path: str,
    only_old: Sequence[str],
    only_new: Sequence[str],
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
