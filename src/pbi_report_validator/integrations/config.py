"""Configuration from environment variables.

Credentials are only read from the environment (or a local ``.env`` the
user loads into it); there are no config files. The environment mapping is
passed in, so nothing here reads global state.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr

from pbi_report_validator.domain.models import AiMode

POWERBI_ENV_VARS = ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET")


class MissingCredentialsError(Exception):
    """Required environment variables for a feature are not set."""


class PowerBIConfig(BaseModel):
    """Service principal credentials for the Power BI REST API."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: str
    client_id: str
    client_secret: SecretStr


def load_powerbi_config(environ: Mapping[str, str]) -> PowerBIConfig:
    """Read the Power BI service principal settings.

    Args:
        environ: The environment, usually ``os.environ``.

    Raises:
        MissingCredentialsError: One or more variables are missing or empty;
            the message names all of them.
    """
    missing = [name for name in POWERBI_ENV_VARS if not environ.get(name, "").strip()]
    if missing:
        raise MissingCredentialsError(
            "data validation needs these environment variables: " + ", ".join(missing)
        )
    return PowerBIConfig(
        tenant_id=environ["PBI_TENANT_ID"].strip(),
        client_id=environ["PBI_CLIENT_ID"].strip(),
        client_secret=SecretStr(environ["PBI_CLIENT_SECRET"].strip()),
    )


AI_ENV_VAR = "PBI_VALIDATE_AI"
AI_MODEL_ENV_VAR = "PBI_VALIDATE_AI_MODEL"
ANTHROPIC_KEY_ENV_VAR = "ANTHROPIC_API_KEY"
AI_DISABLED = "disabled"
# The latest Claude model; override with PBI_VALIDATE_AI_MODEL.
DEFAULT_AI_MODEL = "claude-opus-5-5"


class InvalidAiConfigError(Exception):
    """``PBI_VALIDATE_AI`` has a value other than off, api or disabled."""


class AiPolicy(BaseModel):
    """The AI default and the kill switch from ``PBI_VALIDATE_AI``.

    ``disabled`` (the kill switch) blocks ``--ai api`` whatever the flags
    say, so admins and CI templates can enforce "no AI".
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    default: AiMode = AiMode.OFF
    disabled: bool = False


class AnthropicConfig(BaseModel):
    """The user's Anthropic API key and the model to use."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    api_key: SecretStr
    model: str


def load_ai_policy(environ: Mapping[str, str]) -> AiPolicy:
    """Read ``PBI_VALIDATE_AI`` (``off``, ``api`` or ``disabled``; unset is off).

    Raises:
        InvalidAiConfigError: The variable has any other value.
    """
    value = environ.get(AI_ENV_VAR, "").strip().lower()
    if value == AI_DISABLED:
        return AiPolicy(disabled=True)
    allowed = [*AiMode, AI_DISABLED]
    if value and value not in allowed:
        raise InvalidAiConfigError(
            f"{AI_ENV_VAR} must be one of {', '.join(allowed)}, not '{value}'"
        )
    return AiPolicy(default=AiMode(value or AiMode.OFF))


def load_anthropic_config(environ: Mapping[str, str]) -> AnthropicConfig:
    """Read ``ANTHROPIC_API_KEY`` and the optional ``PBI_VALIDATE_AI_MODEL``.

    Raises:
        MissingCredentialsError: The key is missing or empty.
    """
    api_key = environ.get(ANTHROPIC_KEY_ENV_VAR, "").strip()
    if not api_key:
        raise MissingCredentialsError(
            f"--ai api needs {ANTHROPIC_KEY_ENV_VAR}: create a key in the Claude "
            "Console and set it in the environment (the key owner pays for use)"
        )
    model = environ.get(AI_MODEL_ENV_VAR, "").strip() or DEFAULT_AI_MODEL
    return AnthropicConfig(api_key=SecretStr(api_key), model=model)
