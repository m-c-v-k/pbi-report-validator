"""Tell whether a data difference comes from the report or the semantic model.

Three results of one visual are compared: the old report on the old model
(``old``), the new report on the old model (``cross``) and the new report on
the new model (``new``). ``old`` against ``cross`` isolates the report
change, ``cross`` against ``new`` the model change. Pure functions only.
"""

from pbi_report_validator.diff.results import ColumnPairs, compare_results
from pbi_report_validator.domain.models import (
    Attribution,
    DataStatus,
    QueryResult,
    Tolerance,
)

NOT_REPRODUCED = (
    "neither the report change nor the model change alone gives a difference "
    "beyond the tolerance"
)

_BY_SIDES = {
    (True, False): Attribution.REPORT,
    (False, True): Attribution.MODEL,
    (True, True): Attribution.BOTH,
}


def attribute_difference(
    path: str,
    results: tuple[QueryResult, QueryResult, QueryResult],
    keys: ColumnPairs,
    values: ColumnPairs,
    tolerance: Tolerance,
) -> tuple[Attribution, str | None]:
    """The attribution of a visual whose old and new data differ.

    Args:
        path: The visual's ``page/visual`` path.
        results: The ``old``, ``cross`` and ``new`` results, in that order.
        keys: ``(old column, new column)`` pairs to align rows on.
        values: ``(old column, new column)`` value pairs, as for the
            old/new comparison.
        tolerance: Allowed difference for numbers.

    Returns:
        The attribution, and why it is ``unknown`` (otherwise ``None``).
    """
    old, cross, new = results
    report_side = compare_results(path, old, cross, keys, values, tolerance)
    model_side = compare_results(
        path, cross, new, _new_on_both(keys), _new_on_both(values), tolerance
    )
    for label, side in (("report", report_side), ("model", model_side)):
        if side.summary.status is DataStatus.NOT_VALIDATED:
            return Attribution.UNKNOWN, f"the {label} change: {side.summary.reason}"
    differs = (
        report_side.summary.status is DataStatus.DIFFERENT,
        model_side.summary.status is DataStatus.DIFFERENT,
    )
    attribution = _BY_SIDES.get(differs)
    if attribution is None:
        return Attribution.UNKNOWN, NOT_REPRODUCED
    return attribution, None


def _new_on_both(pairs: ColumnPairs) -> list[tuple[str, str]]:
    """The pairs for comparing two results of the new query."""
    return [(new, new) for _, new in pairs]
