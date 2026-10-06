"""Query published semantic models through the Power BI REST API.

Authenticates as a service principal (MSAL client credentials) and runs DAX
with the ``executeQueries`` endpoint, so it works in CI without Windows-only
drivers. Secrets, tokens and result rows are never logged.
"""

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
import msal

from pbi_report_validator.domain.models import CellValue, QueryResult
from pbi_report_validator.integrations.config import PowerBIConfig

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.powerbi.com/v1.0/myorg/"
AUTHORITY_URL = "https://login.microsoftonline.com/{tenant_id}"
SCOPE = "https://analysis.windows.net/powerbi/api/.default"
DEFAULT_TIMEOUT_SECONDS = 120.0
DEFAULT_MAX_RETRIES = 3
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class PowerBIError(Exception):
    """Base class for Power BI API errors."""


class AuthenticationError(PowerBIError):
    """The service principal could not sign in or is not allowed."""


class DatasetNotFoundError(PowerBIError):
    """The dataset does not exist or the service principal cannot see it."""


class QueryError(PowerBIError):
    """The DAX query was rejected; the message is the engine's error."""


class RateLimitError(PowerBIError):
    """The API kept returning 429 after all retries."""


class ServiceError(PowerBIError):
    """The API failed (5xx, timeout or an unreadable response)."""


class TokenProvider(Protocol):
    """Something that returns a bearer token for the Power BI API."""

    def get_token(self) -> str:
        """Return a valid access token."""
        ...


class MsalTokenProvider:
    """Client-credentials tokens from Microsoft Entra ID via MSAL.

    MSAL caches the token in memory and refreshes it when it expires.
    """

    def __init__(self, config: PowerBIConfig) -> None:
        """Create the MSAL application for the service principal."""
        self._app = msal.ConfidentialClientApplication(
            config.client_id,
            authority=AUTHORITY_URL.format(tenant_id=config.tenant_id),
            client_credential=config.client_secret.get_secret_value(),
        )

    def get_token(self) -> str:
        """Return a token, or raise ``AuthenticationError``."""
        result: dict[str, Any] = self._app.acquire_token_for_client(scopes=[SCOPE])
        token = result.get("access_token")
        if isinstance(token, str):
            return token
        reason = result.get("error_description") or result.get("error") or "unknown"
        raise AuthenticationError(f"could not sign in to Power BI: {reason}")


class PowerBIClient:
    """Runs DAX queries against datasets with ``executeQueries``."""

    def __init__(
        self,
        http: httpx.Client,
        tokens: TokenProvider,
        max_retries: int = DEFAULT_MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a client.

        Args:
            http: HTTP client with ``base_url`` set to the API root.
            tokens: Source of bearer tokens.
            max_retries: Retries for 429, 5xx and timeouts.
            sleep: Wait function, replaceable in tests.
        """
        self._http = http
        self._tokens = tokens
        self._max_retries = max_retries
        self._sleep = sleep

    def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
        """Run one DAX query and return its first result table.

        Raises:
            AuthenticationError: Sign-in failed or access was denied.
            DatasetNotFoundError: The dataset is unknown or not visible.
            QueryError: The query is invalid or failed in the engine.
            RateLimitError: Still rate limited after all retries.
            ServiceError: Server errors, timeouts or unreadable responses.
        """
        body = {
            "queries": [{"query": dax}],
            "serializerSettings": {"includeNulls": True},
        }
        response = self._post(f"datasets/{dataset_id}/executeQueries", body)
        return _parse_result(_json(response))

    def _post(self, path: str, body: dict[str, Any]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            headers = {"Authorization": f"Bearer {self._tokens.get_token()}"}
            try:
                response = self._http.post(path, json=body, headers=headers)
            except httpx.TimeoutException as exc:
                if attempt == self._max_retries:
                    raise ServiceError("Power BI API timed out") from exc
                self._wait(attempt, None)
                continue
            except httpx.HTTPError as exc:
                raise ServiceError(f"could not reach the Power BI API: {exc}") from exc
            if response.status_code in RETRY_STATUSES and attempt < self._max_retries:
                self._wait(attempt, response.headers.get("Retry-After"))
                continue
            _raise_for_status(response)
            return response
        raise ServiceError("Power BI API retries exhausted")  # pragma: no cover

    def _wait(self, attempt: int, retry_after: str | None) -> None:
        delay = (
            float(retry_after)
            if retry_after and retry_after.isdigit()
            else 2.0**attempt
        )
        logger.info("Power BI API busy, retrying in %.0f s", delay)
        self._sleep(delay)


def create_client(config: PowerBIConfig) -> PowerBIClient:
    """Build a client for the public Power BI API with MSAL authentication."""
    http = httpx.Client(base_url=API_BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS)
    return PowerBIClient(http, MsalTokenProvider(config))


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    message = _error_message(response)
    if status in (401, 403):
        raise AuthenticationError(f"access denied by Power BI ({status}): {message}")
    if status == 404:
        raise DatasetNotFoundError(f"dataset not found or not shared: {message}")
    if status == 429:
        raise RateLimitError("Power BI API rate limit reached")
    if status >= 500:
        raise ServiceError(f"Power BI API error {status}: {message}")
    raise QueryError(message)


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ServiceError("Power BI API returned invalid JSON") from exc


def _parse_result(payload: Any) -> QueryResult:
    try:
        result = payload["results"][0]
    except (KeyError, IndexError, TypeError) as exc:
        raise ServiceError("unexpected executeQueries response") from exc
    if isinstance(result, dict) and "error" in result:
        raise QueryError(_message_from(result["error"]))
    tables = result.get("tables") if isinstance(result, dict) else None
    rows = tables[0].get("rows", []) if isinstance(tables, list) and tables else []
    return _table(rows if isinstance(rows, list) else [])


def _table(rows: list[Any]) -> QueryResult:
    columns: list[str] = []
    for row in rows:
        if isinstance(row, dict):
            columns += [name for name in row if name not in columns]
    values = tuple(
        tuple(_cell(row.get(name)) for name in columns)
        for row in rows
        if isinstance(row, dict)
    )
    return QueryResult(columns=tuple(columns), rows=values)


def _cell(value: Any) -> CellValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500] or response.reason_phrase
    return _message_from(payload.get("error") if isinstance(payload, dict) else None)


def _message_from(error: Any) -> str:
    """Pull the most specific message out of a Power BI error object."""
    if not isinstance(error, dict):
        return "unknown error"
    details = error.get("pbi.error", {}).get("details", [])
    for detail in details if isinstance(details, list) else []:
        value = (
            detail.get("detail", {}).get("value") if isinstance(detail, dict) else None
        )
        if isinstance(value, str) and value:
            return value
    message = error.get("message") or error.get("code")
    return str(message) if message else "unknown error"
