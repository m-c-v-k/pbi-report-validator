"""The optional AI layer: resolve ``--ai`` and contain AI failures.

AI is off unless asked for. ``PBI_VALIDATE_AI=disabled`` blocks it whatever
the flags say. Every check runs before the validation, so a missing extra
or key is a usage error and never a failure halfway through a run; a
failing AI call during a run becomes an ``info`` finding.
"""

import logging
from collections.abc import Callable, Mapping

from pbi_report_validator.diff.severity import make_finding
from pbi_report_validator.domain.models import (
    AiMode,
    AiSettings,
    AiSuggestion,
    Category,
    ChangeKind,
    DiffResult,
    Finding,
)
from pbi_report_validator.integrations.anthropic_client import (
    AiError,
    LlmClient,
    create_llm_client,
    ensure_available,
)
from pbi_report_validator.integrations.config import (
    AI_DISABLED,
    AI_ENV_VAR,
    InvalidAiConfigError,
    load_ai_policy,
    load_anthropic_config,
)
from pbi_report_validator.matching.ai_match import (
    InvalidAiResponseError,
    build_match_prompt,
    match_candidates,
    parse_suggestions,
)
from pbi_report_validator.reporting.ai_payload import build_payload

logger = logging.getLogger(__name__)


class InvalidAiOptionsError(ValueError):
    """The AI options conflict with each other or with ``PBI_VALIDATE_AI``."""


def ai_settings(
    requested: AiMode | None,
    allow_data: bool,
    environ: Mapping[str, str],
    match: bool = False,
) -> AiSettings:
    """Settings from ``--ai``, ``--allow-data-to-llm`` and the environment.

    Args:
        requested: The ``--ai`` value; ``None`` uses ``PBI_VALIDATE_AI``.
        allow_data: ``--allow-data-to-llm``.
        environ: The environment, usually ``os.environ``.
        match: ``--ai-match``.

    Raises:
        InvalidAiOptionsError: AI is disabled by the kill switch, the
            variable is invalid (unless ``--ai off`` is given), or
            ``allow_data`` or ``match`` is set without AI.
        AiUnavailableError: ``api`` without the ``[ai]`` extra.
        MissingCredentialsError: ``api`` without ``ANTHROPIC_API_KEY``.
    """
    if requested is AiMode.OFF and not (allow_data or match):
        return AiSettings()
    try:
        policy = load_ai_policy(environ)
    except InvalidAiConfigError as exc:
        raise InvalidAiOptionsError(str(exc)) from exc
    mode = requested or policy.default
    if mode is AiMode.API and policy.disabled:
        raise InvalidAiOptionsError(
            f"--ai api is not allowed: AI is disabled by {AI_ENV_VAR}={AI_DISABLED}"
        )
    for flag, used in (("--allow-data-to-llm", allow_data), ("--ai-match", match)):
        if used and mode is not AiMode.API:
            raise InvalidAiOptionsError(f"{flag} needs --ai api")
    if mode is AiMode.OFF:
        return AiSettings()
    ensure_available()
    config = load_anthropic_config(environ)
    return AiSettings(mode=mode, model=config.model, allow_data=allow_data, match=match)


def llm_client(ai: AiSettings, environ: Mapping[str, str]) -> LlmClient | None:
    """The Anthropic client when an AI feature is on, else ``None``.

    Raises:
        AiUnavailableError: The ``[ai]`` extra is not installed.
        MissingCredentialsError: ``ANTHROPIC_API_KEY`` is not set.
    """
    if not ai.match:
        return None
    return create_llm_client(load_anthropic_config(environ))


def with_match_suggestions(
    result: DiffResult, client: LlmClient, allow_data: bool
) -> DiffResult:
    """``result`` plus AI rename suggestions for its removed and added objects.

    Findings and severities stay as they are. A failed or unusable AI answer
    adds an ``info`` finding instead of suggestions.

    Args:
        result: The deterministic result.
        client: Answers the prompt.
        allow_data: Whether row-level values may be sent (``--allow-data-to-llm``).

    Returns:
        A new result; ``result`` itself when nothing could be paired.
    """
    candidates = match_candidates(build_payload(result, allow_data).findings)
    if not candidates.pairable:
        return result

    def suggest() -> list[AiSuggestion]:
        return parse_suggestions(
            client.complete(*build_match_prompt(candidates)), candidates
        )

    outcome = guarded(suggest, "ai/match")
    if isinstance(outcome, Finding):
        return DiffResult.model_validate(
            {**dict(result), "findings": (*result.findings, outcome)}
        )
    logger.info("AI suggested %d renames", len(outcome))
    return DiffResult.model_validate({**dict(result), "ai_suggestions": tuple(outcome)})


def guarded[T](call: Callable[[], T], path: str) -> T | Finding:
    """Run an AI call; a failure becomes an ``info`` finding, never a crash.

    Args:
        call: The AI step, e.g. explaining one finding.
        path: Where the finding points, e.g. ``ai/explanations``.

    Returns:
        The call's result, or the finding that says why AI was not applied.
    """
    try:
        return call()
    except (AiError, InvalidAiResponseError) as exc:
        logger.warning("AI step %s failed: %s", path, exc)
        return make_finding(
            Category.AI,
            ChangeKind.ERROR,
            path=path,
            message=f"AI (not applied): {exc}",
        )
