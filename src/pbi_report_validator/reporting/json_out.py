"""Render a ``DiffResult`` or ``ChangedResult`` as JSON."""

from pbi_report_validator.domain.models import ChangedResult, DiffResult


def to_json(result: DiffResult | ChangedResult) -> str:
    """Serialise a result as indented JSON with a trailing newline.

    The output is deterministic: findings and projects are already sorted
    by the models and field order follows the model definitions.
    """
    return result.model_dump_json(indent=2) + "\n"
