import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from pbi_report_validator.domain.models import QueryResult
from pbi_report_validator.integrations import powerbi
from pbi_report_validator.integrations.config import PowerBIConfig
from pbi_report_validator.integrations.powerbi import (
    API_BASE_URL,
    AuthenticationError,
    DatasetNotFoundError,
    InvalidDatasetIdError,
    MsalTokenProvider,
    PowerBIClient,
    QueryError,
    RateLimitError,
    ServiceError,
)

DATASET = "00000000-0000-0000-0000-000000000001"
DAX = 'EVALUATE ROW("Total", [Total Sales])'


class FakeTokens:
    def __init__(self) -> None:
        self.calls = 0

    def get_token(self) -> str:
        self.calls += 1
        return "test-token"


def ok_rows(*rows: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"results": [{"tables": [{"rows": list(rows)}]}]})


def client(
    *responses: httpx.Response | Exception,
    sleeps: list[float] | None = None,
    requests: list[httpx.Request] | None = None,
) -> PowerBIClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    http = httpx.Client(base_url=API_BASE_URL, transport=httpx.MockTransport(handler))
    record: Callable[[float], None] = (
        sleeps.append if sleeps is not None else lambda _: None
    )
    return PowerBIClient(http, FakeTokens(), max_retries=2, sleep=record)


def test_query_returns_columns_and_rows_in_order() -> None:
    requests: list[httpx.Request] = []
    pbi = client(
        ok_rows(
            {"Date[Month]": "2025-01", "[Total Sales]": 1280.0},
            {"Date[Month]": "2025-02", "[Total Sales]": None},
        ),
        requests=requests,
    )

    result = pbi.execute_query(DATASET, DAX)

    assert result == QueryResult(
        columns=("Date[Month]", "[Total Sales]"),
        rows=(("2025-01", 1280.0), ("2025-02", None)),
    )
    sent = requests[0]
    assert str(sent.url) == f"{API_BASE_URL}datasets/{DATASET}/executeQueries"
    assert sent.headers["Authorization"] == "Bearer test-token"
    body = json.loads(sent.content)
    assert body == {
        "queries": [{"query": DAX}],
        "serializerSettings": {"includeNulls": True},
    }


def test_columns_missing_in_some_rows_become_none() -> None:
    result = client(ok_rows({"[A]": 1}, {"[A]": 2, "[B]": "x"})).execute_query(
        DATASET, DAX
    )

    assert result.columns == ("[A]", "[B]")
    assert result.rows == ((1, None), (2, "x"))


def test_empty_result() -> None:
    assert client(ok_rows()).execute_query(DATASET, DAX) == QueryResult()


def test_dax_error_in_result_body_is_query_error() -> None:
    body = {
        "results": [{"error": {"code": "QueryError", "message": "Column X not found"}}]
    }

    with pytest.raises(QueryError, match="Column X not found"):
        client(httpx.Response(200, json=body)).execute_query(DATASET, DAX)


def test_bad_request_uses_detailed_engine_message() -> None:
    body = {
        "error": {
            "code": "DatasetExecuteQueriesError",
            "pbi.error": {
                "details": [{"detail": {"value": "Syntax error near EVALUATE"}}]
            },
        }
    }

    with pytest.raises(QueryError, match="Syntax error near EVALUATE"):
        client(httpx.Response(400, json=body)).execute_query(DATASET, DAX)


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AuthenticationError),
        (403, AuthenticationError),
        (404, DatasetNotFoundError),
    ],
)
def test_status_codes_map_to_typed_errors(status: int, error: type[Exception]) -> None:
    response = httpx.Response(status, json={"error": {"code": "X", "message": "nope"}})

    with pytest.raises(error):
        client(response).execute_query(DATASET, DAX)


def test_rate_limit_is_retried_honouring_retry_after() -> None:
    sleeps: list[float] = []
    pbi = client(
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503),
        ok_rows({"[A]": 1}),
        sleeps=sleeps,
    )

    assert pbi.execute_query(DATASET, DAX).rows == ((1,),)
    assert sleeps == [7.0, 2.0]


def test_persistent_rate_limit_raises() -> None:
    responses = [httpx.Response(429) for _ in range(3)]

    with pytest.raises(RateLimitError):
        client(*responses).execute_query(DATASET, DAX)


def test_persistent_server_error_raises_service_error() -> None:
    with pytest.raises(ServiceError, match="500"):
        client(*[httpx.Response(500) for _ in range(3)]).execute_query(DATASET, DAX)


def test_timeouts_are_retried_then_raised() -> None:
    timeout = httpx.ReadTimeout("slow")
    sleeps: list[float] = []

    with pytest.raises(ServiceError, match="timed out"):
        client(timeout, timeout, timeout, sleeps=sleeps).execute_query(DATASET, DAX)
    assert sleeps == [1.0, 2.0]


def test_connection_error_is_service_error() -> None:
    with pytest.raises(ServiceError, match="could not reach"):
        client(httpx.ConnectError("no network")).execute_query(DATASET, DAX)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"unexpected": True}),
    ],
)
def test_unreadable_response_is_service_error(response: httpx.Response) -> None:
    with pytest.raises(ServiceError):
        client(response).execute_query(DATASET, DAX)


class FakeMsalApp:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.init: dict[str, Any] = {}

    def __call__(self, client_id: str, **kwargs: Any) -> "FakeMsalApp":
        self.init = {"client_id": client_id, **kwargs}
        return self

    def acquire_token_for_client(self, scopes: list[str]) -> dict[str, Any]:
        assert scopes == [powerbi.SCOPE]
        return self.result


CONFIG = PowerBIConfig(
    tenant_id="tenant-123", client_id="client-456", client_secret=SecretStr("s3cret")
)


def test_msal_provider_returns_token(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMsalApp({"access_token": "abc"})
    monkeypatch.setattr(powerbi.msal, "ConfidentialClientApplication", fake)

    assert MsalTokenProvider(CONFIG).get_token() == "abc"
    assert fake.init == {
        "client_id": "client-456",
        "authority": "https://login.microsoftonline.com/tenant-123",
        "client_credential": "s3cret",
    }


def test_msal_failure_is_authentication_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMsalApp({"error": "invalid_client", "error_description": "bad secret"})
    monkeypatch.setattr(powerbi.msal, "ConfidentialClientApplication", fake)

    with pytest.raises(AuthenticationError, match="bad secret"):
        MsalTokenProvider(CONFIG).get_token()


def test_secret_is_not_in_config_repr() -> None:
    assert "s3cret" not in repr(CONFIG)


@pytest.mark.parametrize(
    "dataset_id", ["../x", "abc", f"{DATASET}/x", f"{DATASET}?a=1"]
)
def test_non_guid_dataset_id_is_rejected_before_any_request(dataset_id: str) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(InvalidDatasetIdError):
        client(ok_rows(), requests=requests).execute_query(dataset_id, DAX)
    assert requests == []


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("86400", 60.0), ("Wed, 21 Oct 2026 07:28:00 GMT", 1.0), ("soon", 1.0)],
)
def test_retry_after_is_capped_and_non_numeric_falls_back(
    retry_after: str, expected: float
) -> None:
    sleeps: list[float] = []
    pbi = client(
        httpx.Response(429, headers={"Retry-After": retry_after}),
        ok_rows({"[A]": 1}),
        sleeps=sleeps,
    )

    pbi.execute_query(DATASET, DAX)

    assert sleeps == [expected]


def test_bad_request_with_non_json_body_is_query_error() -> None:
    with pytest.raises(QueryError, match="plain text failure"):
        client(httpx.Response(400, text="plain text failure")).execute_query(
            DATASET, DAX
        )


class RaisingMsalApp(FakeMsalApp):
    def acquire_token_for_client(self, scopes: list[str]) -> dict[str, Any]:
        raise ConnectionError("login.microsoftonline.com unreachable")


def test_msal_network_failure_is_service_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        powerbi.msal, "ConfidentialClientApplication", RaisingMsalApp({})
    )

    with pytest.raises(ServiceError, match="could not reach Microsoft Entra ID"):
        MsalTokenProvider(CONFIG).get_token()
