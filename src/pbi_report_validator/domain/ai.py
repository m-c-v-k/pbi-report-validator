"""Settings of the optional AI layer."""

from enum import StrEnum

from pbi_report_validator.domain.base import DomainModel


class AiMode(StrEnum):
    """Values of ``--ai``: no AI, or the Anthropic API with the user's own key."""

    OFF = "off"
    API = "api"


class AiSettings(DomainModel):
    """How the AI layer runs for one validation.

    ``model`` is set when ``mode`` is ``api``. ``allow_data`` lets row-level
    values reach the model (``--allow-data-to-llm``); by default only
    metadata is sent.
    """

    mode: AiMode = AiMode.OFF
    model: str | None = None
    allow_data: bool = False
