"""AI match suggestions: which removed object was probably renamed to which added one.

Runs only on what the deterministic matcher left unmatched: removed and
added pages, visuals and measures. The model sees the metadata-only AI
payload of those findings and answers with JSON in the shape of
``match_response_schema()``, which the request also passes as a structured
output format. The answer is still validated, and every suggestion is
checked against the candidates, so the model can only pair objects that
really were removed and added. Pure functions only: the model call itself
happens in ``services``.
"""

import json
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pbi_report_validator.domain.base import DomainModel
from pbi_report_validator.domain.models import (
    AiFinding,
    AiSuggestion,
    Category,
    ChangeKind,
)

MATCHABLE: Final = (Category.PAGE, Category.VISUAL, Category.MEASURE)

SYSTEM_PROMPT: Final = """\
You compare two versions of a Power BI report. A deterministic matcher has \
already paired everything it could; what is left was reported as removed or \
added. Decide which removed object was most likely renamed (or replaced by) \
which added object of the same category.

Answer with JSON only, no other text, in this shape:
{"suggestions": [{"old_path": "...", "new_path": "...", \
"confidence": 0.0, "reason": "..."}]}

Rules:
- old_path is the path of a removed object, new_path of an added object of \
the same category, both copied exactly from the input.
- Use each path at most once. Leave out pairs you are not reasonably sure \
about; an empty list is a valid answer.
- confidence is between 0 and 1. reason is one short sentence for a reviewer.
"""


class InvalidAiResponseError(ValueError):
    """The model's answer is not usable JSON in the expected shape."""


class MatchCandidates(DomainModel):
    """The removed and added findings the AI may pair."""

    removed: tuple[AiFinding, ...] = ()
    added: tuple[AiFinding, ...] = ()

    @property
    def pairable(self) -> bool:
        """Whether some category has both a removed and an added object."""
        removed = {f.category for f in self.removed}
        return any(f.category in removed for f in self.added)


class _Answer(BaseModel):
    """One pair as the model wrote it; extra keys are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    old_path: str
    new_path: str
    confidence: float = Field(allow_inf_nan=False)
    reason: str


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    suggestions: tuple[_Answer, ...] = ()


def match_response_schema() -> dict[str, object]:
    """The JSON schema of the answer ``parse_suggestions`` expects."""
    return _Response.model_json_schema()


def match_candidates(findings: tuple[AiFinding, ...]) -> MatchCandidates:
    """Removed and added pages, visuals and measures from the AI payload."""
    matchable = [f for f in findings if f.category in MATCHABLE]
    return MatchCandidates(
        removed=tuple(f for f in matchable if f.change is ChangeKind.REMOVED),
        added=tuple(f for f in matchable if f.change is ChangeKind.ADDED),
    )


def build_match_prompt(candidates: MatchCandidates) -> tuple[str, str]:
    """The system prompt and the user prompt for ``candidates``."""
    payload = candidates.model_dump(mode="json", exclude_none=True)
    return SYSTEM_PROMPT, json.dumps(payload, indent=1, sort_keys=True)


def parse_suggestions(text: str, candidates: MatchCandidates) -> list[AiSuggestion]:
    """Turn the model's answer into suggestions between real candidates.

    Pairs that name an unknown path, cross categories or reuse a path are
    dropped; a confidence outside 0-1 is clamped.

    Raises:
        InvalidAiResponseError: The answer is not JSON in the asked shape.
    """
    response = _response(text)
    removed = {f.path: f.category for f in candidates.removed}
    added = {f.path: f.category for f in candidates.added}
    used: set[str] = set()
    suggestions = []
    for answer in response.suggestions:
        category = removed.get(answer.old_path)
        if category is None or added.get(answer.new_path) is not category:
            continue
        if {answer.old_path, answer.new_path} & used:
            continue
        used |= {answer.old_path, answer.new_path}
        suggestions.append(_suggestion(answer, category))
    return suggestions


def _response(text: str) -> _Response:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise InvalidAiResponseError("the model's answer contained no JSON object")
    try:
        return _Response.model_validate_json(text[start : end + 1])
    except ValidationError as exc:
        raise InvalidAiResponseError(
            f"the model's answer did not have the expected shape "
            f"({exc.error_count()} errors)"
        ) from exc


def _suggestion(answer: _Answer, category: Category) -> AiSuggestion:
    return AiSuggestion(
        category=category,
        old_path=answer.old_path,
        new_path=answer.new_path,
        confidence=min(1.0, max(0.0, answer.confidence)),
        reason=" ".join(answer.reason.split()),
    )
