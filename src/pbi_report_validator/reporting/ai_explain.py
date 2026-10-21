"""AI explanations: findings rewritten as a sentence a tester understands.

The model sees the metadata-only AI payload of the chosen findings, each
under a short id, and answers with JSON keyed by those ids; explanations
for unknown ids are dropped. Pure functions only: choosing the findings
and the model call happen in ``services``.
"""

import json
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError

from pbi_report_validator.domain.models import AiFinding

MAX_TEXT: Final = 600

SYSTEM_PROMPT: Final = """\
You explain differences between two versions of a Power BI report to a \
tester who knows the report but not its JSON or DAX. Each finding has an id, \
what changed and where, and sometimes the old and new value.

For each finding, write one or two plain sentences: what changed and what it \
probably means for what a user sees or for the numbers. Use only facts from \
the finding; say "may" when you infer an effect.

Answer with JSON only, no other text, in this shape:
{"explanations": [{"id": "f1", "text": "..."}]}
"""


class InvalidAiExplanationError(ValueError):
    """The model's answer is not usable JSON in the expected shape."""


class _Explanation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    text: str


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    explanations: tuple[_Explanation, ...] = ()


def finding_ids(indices: list[int]) -> dict[str, int]:
    """Short prompt ids (``f1``, ``f2``, ...) for finding indices, in order."""
    return {f"f{n}": index for n, index in enumerate(sorted(indices), start=1)}


def build_explain_prompt(
    findings: tuple[AiFinding, ...], ids: dict[str, int]
) -> tuple[str, str]:
    """The system prompt and the user prompt for the chosen findings."""
    chosen = [
        {"id": key, **findings[index].model_dump(mode="json", exclude_none=True)}
        for key, index in ids.items()
    ]
    return SYSTEM_PROMPT, json.dumps({"findings": chosen}, indent=1, sort_keys=True)


def parse_explanations(text: str, ids: dict[str, int]) -> dict[int, str]:
    """Explanation texts by finding index; unknown ids and blanks are dropped.

    Raises:
        InvalidAiExplanationError: The answer is not JSON in the asked shape.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise InvalidAiExplanationError("the model's answer contained no JSON object")
    try:
        response = _Response.model_validate_json(text[start : end + 1])
    except ValidationError as exc:
        raise InvalidAiExplanationError(
            f"the model's answer did not have the expected shape "
            f"({exc.error_count()} errors)"
        ) from exc
    texts = {}
    for item in response.explanations:
        clean = _shortened(" ".join(item.text.split()))
        if item.id in ids and clean and ids[item.id] not in texts:
            texts[ids[item.id]] = clean
    return texts


def _shortened(text: str) -> str:
    if len(text) <= MAX_TEXT:
        return text
    return text[: MAX_TEXT - 1].rstrip() + "…"
