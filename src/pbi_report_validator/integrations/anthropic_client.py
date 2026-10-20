"""Optional client for the Anthropic API (the ``[ai]`` extra).

The core depends only on the ``LlmClient`` protocol; ``anthropic`` is
imported when a client is created, so every command works without the
extra installed. The API key, prompts and responses are never logged.
"""

import importlib.util
import logging
from typing import TYPE_CHECKING, Protocol

from pbi_report_validator.integrations.config import AnthropicConfig

if TYPE_CHECKING:
    import anthropic
    import httpx2

logger = logging.getLogger(__name__)

INSTALL_HINT = (
    'install the "ai" extra, e.g. uv tool install "pbi-report-validator[ai] @ '
    'git+https://github.com/m-c-v-k/pbi-report-validator"'
)
TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 2
MAX_TOKENS = 16_000


class AiError(Exception):
    """Base class for AI layer errors."""


class AiUnavailableError(AiError):
    """The ``anthropic`` package (the ``[ai]`` extra) is not installed."""


class AiAuthenticationError(AiError):
    """The API key was rejected or lacks permission."""


class AiRateLimitError(AiError):
    """The API kept returning 429 after the SDK's retries."""


class AiServiceError(AiError):
    """The API failed (5xx), timed out or could not be reached."""


class AiRequestError(AiError):
    """The API rejected the request or returned no usable answer."""


class LlmClient(Protocol):
    """Something that answers a prompt (the Anthropic client in production)."""

    def complete(self, system: str, prompt: str) -> str:
        """Return the model's text answer to ``prompt``."""
        ...


def ensure_available() -> None:
    """Check that the ``[ai]`` extra is installed.

    Raises:
        AiUnavailableError: ``anthropic`` cannot be imported.
    """
    if importlib.util.find_spec("anthropic") is None:
        raise AiUnavailableError(
            f"--ai api needs the anthropic package: {INSTALL_HINT}"
        )


def create_llm_client(
    config: AnthropicConfig, http_client: "httpx2.Client | None" = None
) -> LlmClient:
    """An Anthropic client for ``config``.

    Args:
        config: API key and model.
        http_client: Transport override, for tests.

    Raises:
        AiUnavailableError: The ``[ai]`` extra is not installed.
    """
    ensure_available()
    import anthropic

    sdk = anthropic.Anthropic(
        api_key=config.api_key.get_secret_value(),
        timeout=TIMEOUT_SECONDS,
        max_retries=MAX_RETRIES,
        http_client=http_client,
    )
    return AnthropicClient(sdk, config.model)


class AnthropicClient:
    """Single-turn text completions through the Messages API."""

    def __init__(self, sdk: "anthropic.Anthropic", model: str) -> None:
        """Wrap an SDK client; ``model`` is the Claude model id."""
        self._sdk = sdk
        self._model = model

    def complete(self, system: str, prompt: str) -> str:
        """Return the model's text answer to ``prompt``.

        Raises:
            AiAuthenticationError: The key was rejected.
            AiRateLimitError: Rate limited after retries.
            AiServiceError: Server error, timeout or no connection.
            AiRequestError: The request was rejected, refused or cut off.
        """
        import anthropic

        try:
            message = self._sdk.messages.create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise AiAuthenticationError(
                "the Anthropic API rejected ANTHROPIC_API_KEY"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise AiRateLimitError("the Anthropic API rate limit was hit") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise AiServiceError(
                    f"the Anthropic API failed (HTTP {exc.status_code})"
                ) from exc
            raise AiRequestError(
                f"the Anthropic API rejected the request (HTTP {exc.status_code})"
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise AiServiceError("the Anthropic API could not be reached") from exc
        logger.info("AI response from %s: %s", self._model, message.stop_reason)
        if message.stop_reason in ("refusal", "max_tokens"):
            raise AiRequestError(f"the model gave no answer ({message.stop_reason})")
        text = "".join(block.text for block in message.content if block.type == "text")
        if not text.strip():
            raise AiRequestError("the model returned no text")
        return text
