"""Configuration from environment variables.

Credentials are only read from the environment (or a local ``.env`` the
user loads into it); there are no config files. The environment mapping is
passed in, so nothing here reads global state.
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr

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
