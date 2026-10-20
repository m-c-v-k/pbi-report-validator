"""Optional client for the Anthropic API (the ``[ai]`` extra).

``anthropic`` is only imported when a client is created, so every command
works without the extra installed.
"""

import importlib.util

INSTALL_HINT = (
    'install the "ai" extra, e.g. uv tool install "pbi-report-validator[ai] @ '
    'git+https://github.com/m-c-v-k/pbi-report-validator"'
)


class AiError(Exception):
    """Base class for AI layer errors."""


class AiUnavailableError(AiError):
    """The ``anthropic`` package (the ``[ai]`` extra) is not installed."""


def ensure_available() -> None:
    """Check that the ``[ai]`` extra is installed.

    Raises:
        AiUnavailableError: ``anthropic`` cannot be imported.
    """
    if importlib.util.find_spec("anthropic") is None:
        raise AiUnavailableError(
            f"--ai api needs the anthropic package: {INSTALL_HINT}"
        )
