import pytest

from pbi_report_validator.domain.models import AiMode, AiSettings
from pbi_report_validator.integrations import anthropic_client
from pbi_report_validator.integrations.anthropic_client import AiUnavailableError
from pbi_report_validator.integrations.config import (
    DEFAULT_AI_MODEL,
    MissingCredentialsError,
)
from pbi_report_validator.services.ai import InvalidAiOptionsError, ai_settings

KEY = {"ANTHROPIC_API_KEY": "test-key"}


def test_off_by_default_without_reading_anything() -> None:
    assert ai_settings(None, False, {}) == AiSettings()
    assert ai_settings(AiMode.OFF, False, {}) == AiSettings()


def test_api_uses_the_latest_model_by_default() -> None:
    settings = ai_settings(AiMode.API, False, KEY)

    assert settings == AiSettings(mode=AiMode.API, model=DEFAULT_AI_MODEL)
    assert DEFAULT_AI_MODEL == "claude-opus-5-5"


def test_model_and_default_mode_come_from_the_environment() -> None:
    environ = {
        **KEY,
        "PBI_VALIDATE_AI": "API",
        "PBI_VALIDATE_AI_MODEL": "claude-other",
    }

    settings = ai_settings(None, True, environ)

    assert settings == AiSettings(
        mode=AiMode.API, model="claude-other", allow_data=True
    )


def test_flag_overrides_the_environment_default() -> None:
    assert ai_settings(AiMode.OFF, False, {"PBI_VALIDATE_AI": "api"}) == AiSettings()


def test_kill_switch_blocks_api_and_names_the_variable() -> None:
    environ = {**KEY, "PBI_VALIDATE_AI": "disabled"}

    with pytest.raises(InvalidAiOptionsError, match="PBI_VALIDATE_AI=disabled"):
        ai_settings(AiMode.API, False, environ)
    assert ai_settings(None, False, environ) == AiSettings()
    assert ai_settings(AiMode.OFF, False, environ) == AiSettings()


def test_unknown_environment_value_is_rejected() -> None:
    with pytest.raises(InvalidAiOptionsError, match="PBI_VALIDATE_AI must be one of"):
        ai_settings(None, False, {"PBI_VALIDATE_AI": "maybe"})


def test_allow_data_needs_api() -> None:
    with pytest.raises(InvalidAiOptionsError, match="needs --ai api"):
        ai_settings(None, True, KEY)


@pytest.mark.parametrize("environ", [{}, {"ANTHROPIC_API_KEY": "  "}])
def test_api_without_key_explains_setup(environ: dict[str, str]) -> None:
    with pytest.raises(MissingCredentialsError, match="ANTHROPIC_API_KEY"):
        ai_settings(AiMode.API, False, environ)


def test_api_without_extra_explains_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(anthropic_client.importlib.util, "find_spec", lambda _: None)

    with pytest.raises(AiUnavailableError, match="install"):
        ai_settings(AiMode.API, False, KEY)
