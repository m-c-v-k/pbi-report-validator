"""The optional AI layer: resolve ``--ai`` against the environment.

AI is off unless asked for. ``PBI_VALIDATE_AI=disabled`` blocks it whatever
the flags say. Every check runs before the validation, so a missing extra
or key is a usage error and never a failure halfway through a run.
"""

from collections.abc import Mapping

from pbi_report_validator.domain.models import AiMode, AiSettings
from pbi_report_validator.integrations.anthropic_client import ensure_available
from pbi_report_validator.integrations.config import (
    AI_DISABLED,
    AI_ENV_VAR,
    InvalidAiConfigError,
    load_ai_policy,
    load_anthropic_config,
)


class InvalidAiOptionsError(ValueError):
    """The AI options conflict with each other or with ``PBI_VALIDATE_AI``."""


def ai_settings(
    requested: AiMode | None, allow_data: bool, environ: Mapping[str, str]
) -> AiSettings:
    """Settings from ``--ai``, ``--allow-data-to-llm`` and the environment.

    Args:
        requested: The ``--ai`` value; ``None`` uses ``PBI_VALIDATE_AI``.
        allow_data: ``--allow-data-to-llm``.
        environ: The environment, usually ``os.environ``.

    Raises:
        InvalidAiOptionsError: AI is disabled by the kill switch, the
            variable is invalid, or ``allow_data`` is set without AI.
        AiUnavailableError: ``api`` without the ``[ai]`` extra.
        MissingCredentialsError: ``api`` without ``ANTHROPIC_API_KEY``.
    """
    try:
        policy = load_ai_policy(environ)
    except InvalidAiConfigError as exc:
        raise InvalidAiOptionsError(str(exc)) from exc
    mode = requested or policy.default
    if mode is AiMode.API and policy.disabled:
        raise InvalidAiOptionsError(
            f"--ai api is not allowed: AI is disabled by {AI_ENV_VAR}={AI_DISABLED}"
        )
    if allow_data and mode is not AiMode.API:
        raise InvalidAiOptionsError("--allow-data-to-llm needs --ai api")
    if mode is AiMode.OFF:
        return AiSettings()
    ensure_available()
    config = load_anthropic_config(environ)
    return AiSettings(mode=mode, model=config.model, allow_data=allow_data)
