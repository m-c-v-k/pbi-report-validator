import json
from collections.abc import Callable

import httpx2
import pytest
from pydantic import SecretStr

from pbi_report_validator.integrations import anthropic_client
from pbi_report_validator.integrations.anthropic_client import (
    AiAuthenticationError,
    AiRateLimitError,
    AiRequestError,
    AiServiceError,
    AiUnavailableError,
    LlmClient,
    create_llm_client,
    ensure_available,
)
from pbi_report_validator.integrations.config import AnthropicConfig

CONFIG = AnthropicConfig(api_key=SecretStr("test-key"), model="claude-test")


def message(
    text: str = "An answer.", stop_reason: str = "end_turn"
) -> dict[str, object]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [{"type": "text", "text": text}] if text else [],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def client_for(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> LlmClient:
    transport = httpx2.MockTransport(handler)
    return create_llm_client(CONFIG, httpx2.Client(transport=transport))


def respond(status: int, body: object) -> LlmClient:
    return client_for(lambda request: httpx2.Response(status, json=body))


def test_sends_system_prompt_and_model_and_returns_text() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=message())

    answer = client_for(handler).complete("Be brief.", "Explain this finding.")

    assert answer == "An answer."
    body = json.loads(requests[0].content)
    assert body["model"] == "claude-test"
    assert body["system"] == "Be brief."
    assert body["messages"] == [{"role": "user", "content": "Explain this finding."}]
    assert requests[0].headers["x-api-key"] == "test-key"
    assert "output_config" not in body


def test_schema_requests_structured_output() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json=message('{"answer": "yes"}'))

    schema = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    answer = client_for(handler).complete("s", "p", schema)

    assert answer == '{"answer": "yes"}'
    output_format = json.loads(requests[0].content)["output_config"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["schema"]["properties"] == schema["properties"]
    assert output_format["schema"]["required"] == ["answer"]
    assert output_format["schema"]["additionalProperties"] is False


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AiAuthenticationError),
        (403, AiAuthenticationError),
        (429, AiRateLimitError),
        (500, AiServiceError),
        (529, AiServiceError),
        (400, AiRequestError),
        (404, AiRequestError),
    ],
)
def test_http_errors_become_typed_errors(
    status: int, error: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(anthropic_client, "MAX_RETRIES", 0)
    body = {"type": "error", "error": {"type": "x", "message": "secret detail"}}

    with pytest.raises(error) as exc_info:
        respond(status, body).complete("s", "p")

    assert "secret detail" not in str(exc_info.value)


def test_connection_failure_is_a_service_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(anthropic_client, "MAX_RETRIES", 0)

    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(AiServiceError, match="could not be reached"):
        client_for(handler).complete("s", "p")


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refused_or_cut_off_answers_are_errors(stop_reason: str) -> None:
    with pytest.raises(AiRequestError, match=stop_reason):
        respond(200, message(stop_reason=stop_reason)).complete("s", "p")


def test_empty_answer_is_an_error() -> None:
    with pytest.raises(AiRequestError, match="no text"):
        respond(200, message(text="")).complete("s", "p")


def test_installed_extra_is_available() -> None:
    ensure_available()


def test_missing_extra_is_reported_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(anthropic_client.importlib.util, "find_spec", lambda _: None)

    with pytest.raises(AiUnavailableError, match=r"pbi-report-validator\[ai\]"):
        ensure_available()
    with pytest.raises(AiUnavailableError):
        create_llm_client(CONFIG)
