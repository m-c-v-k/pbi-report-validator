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
from pbi_report_validator.domain.helpers import field_name, is_within, visual_path
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataComparison,
    DataSettings,
    DataStatus,
    DaxQuery,
    Page,
    PageMatch,
    QueryResult,
    Report,
    ReportMatch,
    Tolerance,
    UnsupportedQuery,
    ValuePairing,
    Visual,
    VisualMatch,
)
from pbi_report_validator.integrations.config import load_powerbi_config
from pbi_report_validator.integrations.powerbi import (
    MAX_RESULT_ROWS,
    MAX_RESULT_VALUES,
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
VISUAL_PARTLY_PARSED = "the visual could not be fully parsed"
PAGE_PARTLY_PARSED = (
    "another visual on the page could not be parsed, so a filter it sets may be missing"
)
LOST_VISUAL = "the visual could not be parsed in the {side} version"
LOST_PAGE = "the page could not be parsed in the {side} version"
SLICER_IN_ONE_VERSION = "the visual is a slicer in only one version"


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
    query cannot be built or fails becomes a ``not_validated`` result, and
    so does one that is incomplete because of a parse issue: its own, one
    of another visual on its page (a lost slicer would leave its filter
    out), or a parse error that lost it, or its page, in one version.

    Raises:
        AuthenticationError: The service principal cannot sign in.
        DatasetNotFoundError: A dataset id is wrong or not shared.
        InvalidDatasetIdError: A dataset id is not a GUID.
    """
    value_renames = _value_renames(renames)
    old_issues, new_issues = _issue_visuals(old), _issue_visuals(new)
    comparisons = []
    for page_match in match.pages:
        page_incomplete = _lost_a_visual(page_match.old, old_issues) or (
            _lost_a_visual(page_match.new, new_issues)
        )
        for visual_match in page_match.visuals:
            if visual_match.old.slicer and visual_match.new.slicer:
                continue
            path = visual_path(page_match.old.name, visual_match.old.name)
            reason = _incomplete_reason(
                page_match, visual_match, old_issues, new_issues, page_incomplete
            )
            if reason:
                comparisons.append(not_validated(path, reason))
                continue
            old_query = build_query(visual_match.old, page_match.old, old.filters)
            new_query = build_query(visual_match.new, page_match.new, new.filters)
            comparisons.append(
                _compare(path, old_query, new_query, value_renames, runner, settings)
            )
        comparisons += _lost_visuals(page_match, old_issues, new_issues)
    comparisons += _lost_pages(match, old, new)
    logger.info("Compared the data of %d visuals", len(comparisons))
    return comparisons


def _issue_visuals(report: Report) -> frozenset[str]:
    """The ``page/visual`` paths of the visuals that have a parse issue."""
    return frozenset(i.visual_path for i in report.issues if i.visual_path)


def _lost_a_visual(page: Page, issue_visuals: frozenset[str]) -> bool:
    """Whether a visual of ``page`` failed to parse and is missing from it."""
    parsed = {visual_path(page.name, v.name) for v in page.visuals}
    return any(is_within(p, page.name) and p not in parsed for p in issue_visuals)


def _incomplete_reason(
    page_match: PageMatch,
    visual_match: VisualMatch,
    old_issues: frozenset[str],
    new_issues: frozenset[str],
    page_incomplete: bool,
) -> str | None:
    """Why a matched visual cannot be compared faithfully, if it cannot."""
    if (visual_match.old.slicer is None) != (visual_match.new.slicer is None):
        return SLICER_IN_ONE_VERSION
    old_key = visual_path(page_match.old.name, visual_match.old.name)
    new_key = visual_path(page_match.new.name, visual_match.new.name)
    if old_key in old_issues or new_key in new_issues:
        return VISUAL_PARTLY_PARSED
    if page_incomplete:
        return PAGE_PARTLY_PARSED
    return None


def _lost_visuals(
    page_match: PageMatch, old_issues: frozenset[str], new_issues: frozenset[str]
) -> list[DataComparison]:
    """Visuals that failed to parse in one version, so were never compared."""
    old_page, new_page = page_match.old.name, page_match.new.name
    lost = [
        not_validated(visual_path(old_page, v.name), LOST_VISUAL.format(side="new"))
        for v in page_match.removed_visuals
        if visual_path(new_page, v.name) in new_issues and _shows_data(v)
    ]
    lost += [
        not_validated(visual_path(old_page, v.name), LOST_VISUAL.format(side="old"))
        for v in page_match.added_visuals
        if visual_path(old_page, v.name) in old_issues and _shows_data(v)
    ]
    return lost


def _lost_pages(match: ReportMatch, old: Report, new: Report) -> list[DataComparison]:
    """Visuals of pages that failed to parse in one version."""
    old_broken = {i.page for i in old.issues if i.page}
    new_broken = {i.page for i in new.issues if i.page}
    sides = [
        ("new", match.removed_pages, new_broken),
        ("old", match.added_pages, old_broken),
    ]
    return [
        not_validated(visual_path(p.name, v.name), LOST_PAGE.format(side=side))
        for side, pages, broken in sides
        for p in pages
        if p.name in broken
        for v in p.visuals
        if _shows_data(v)
    ]


def _shows_data(visual: Visual) -> bool:
    return visual.slicer is None and bool(visual.projections)


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
    if reason := _truncation_reason(old_result, new_result):
        return not_validated(path, reason)
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


def _truncation_reason(old: QueryResult, new: QueryResult) -> str | None:
    """Why a result may be incomplete; the API cuts it off without an error."""
    sides = [
        label for label, result in (("old", old), ("new", new)) if _at_api_limit(result)
    ]
    if not sides:
        return None
    return (
        f"the {' and '.join(sides)} result reached the API limit of "
        f"{MAX_RESULT_ROWS:,} rows or {MAX_RESULT_VALUES:,} values "
        "and may be cut off"
    )


def _at_api_limit(result: QueryResult) -> bool:
    rows = len(result.rows)
    return rows >= MAX_RESULT_ROWS or rows * len(result.columns) >= MAX_RESULT_VALUES


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
    """Note values that exist in only one version, so they are not hidden.

    Matching columns then prove too little for ``same``, so that status
    becomes ``not_validated``; a difference that was found stays ``different``.
    """
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
    status = comparison.summary.status
    if status == DataStatus.SAME:
        status = DataStatus.NOT_VALIDATED
    summary = comparison.summary.model_copy(update={"status": status, "reason": note})
    return DataComparison(summary=summary, findings=(*comparison.findings, finding))


def _value_renames(renames: Mapping[str, str]) -> dict[str, str]:
    """Measure renames by name: ``Sales[Margin %]`` -> ``Margin %``."""
    return {field_name(old): field_name(new) for old, new in renames.items()}
