import pytest

from pbi_report_validator.domain.models import AiMode
from pbi_report_validator.integrations.config import (
    DEFAULT_AI_MODEL,
    AiPolicy,
    InvalidAiConfigError,
    MissingCredentialsError,
    load_ai_policy,
    load_anthropic_config,
    load_powerbi_config,
)

FULL = {
    "PBI_TENANT_ID": " tenant ",
    "PBI_CLIENT_ID": "client",
    "PBI_CLIENT_SECRET": "secret",
}


def test_loads_and_strips_values() -> None:
    config = load_powerbi_config(FULL)

    assert (config.tenant_id, config.client_id) == ("tenant", "client")
    assert config.client_secret.get_secret_value() == "secret"


def test_missing_and_empty_variables_are_all_named() -> None:
    environ = {"PBI_TENANT_ID": "t", "PBI_CLIENT_SECRET": "  "}

    with pytest.raises(MissingCredentialsError) as exc_info:
        load_powerbi_config(environ)

    assert str(exc_info.value).endswith("PBI_CLIENT_ID, PBI_CLIENT_SECRET")


def test_no_credentials_at_all() -> None:
    with pytest.raises(MissingCredentialsError, match="PBI_TENANT_ID"):
        load_powerbi_config({})


def test_ai_policy_defaults_to_off() -> None:
    assert load_ai_policy({}) == AiPolicy()
    assert load_ai_policy({"PBI_VALIDATE_AI": " Api "}) == AiPolicy(default=AiMode.API)
    assert load_ai_policy({"PBI_VALIDATE_AI": "DISABLED"}).disabled


def test_ai_policy_rejects_unknown_values() -> None:
    with pytest.raises(InvalidAiConfigError, match="off, api, disabled"):
        load_ai_policy({"PBI_VALIDATE_AI": "on"})


def test_anthropic_config_keeps_the_key_secret() -> None:
    config = load_anthropic_config({"ANTHROPIC_API_KEY": " sk-test "})

    assert config.api_key.get_secret_value() == "sk-test"
    assert "sk-test" not in repr(config)
    assert config.model == DEFAULT_AI_MODEL
