"""Render a ``DiffResult`` as JSON."""

from pbi_report_validator.domain.models import DiffResult


def to_json(result: DiffResult) -> str:
    """Serialise a result as indented JSON with a trailing newline.

    The output is deterministic: findings are already sorted by
    ``DiffResult`` and field order follows the model definition.
    """
    return result.model_dump_json(indent=2) + "\n"
