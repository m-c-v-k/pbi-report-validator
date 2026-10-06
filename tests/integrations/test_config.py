import pytest

from pbi_report_validator.integrations.config import (
    MissingCredentialsError,
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
