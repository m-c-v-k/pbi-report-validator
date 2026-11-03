"""Record live ``executeQueries`` responses for the replay tests.

Runs the sample reports through the real client against ``sales_v1`` and
``sales_v2`` published as two semantic models, then runs a few queries that
provoke API errors. Dataset ids are replaced by placeholders and the files
are refused if any other GUID is left. Only use this on the synthetic sample
reports. See ``tests/fixtures/README.md``.

Usage, with the ``PBI_*`` variables in the environment::

    uv run python -m tests.record_powerbi_responses <old dataset> <new dataset>
"""

import contextlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from pbi_report_validator.domain.models import DataSettings
from pbi_report_validator.integrations.config import load_powerbi_config
from pbi_report_validator.integrations.powerbi import (
    API_BASE_URL,
    DEFAULT_TIMEOUT_SECONDS,
    MsalTokenProvider,
    PowerBIClient,
    PowerBIError,
)
from pbi_report_validator.services.validate import validate

ROOT = Path(__file__).parent / "fixtures"
RECORDED = ROOT / "recorded"
OLD_PLACEHOLDER = "00000000-0000-0000-0000-000000000001"
NEW_PLACEHOLDER = "00000000-0000-0000-0000-000000000002"
UNKNOWN_DATASET = "00000000-0000-0000-0000-000000000009"
GUID = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
KEPT_ROWS_OF_FAILED_RESULT = 2

ERROR_QUERIES = {
    "empty_result": "EVALUATE FILTER('Date', 'Date'[Year] = 1900)",
    "value_types": 'EVALUATE ROW("int", 1, "dec", 0.1, "bool", TRUE(), '
    '"date", DATE(2025, 1, 15), "blank", BLANK())',
    "unknown_table": "EVALUATE ROW(\"x\", 'Nope'[Nope])",
    "syntax_error": "EVALUATE THIS IS NOT DAX",
    "runtime_error": 'EVALUATE ROW("x", ERROR("boom"))',
    "row_limit": "EVALUATE GENERATESERIES(1, 150000)",
    "value_limit": 'EVALUATE ADDCOLUMNS(GENERATESERIES(1, 90000), "a", 1, "b", 2, '
    '"c", 3, "d", 4, "e", 5, "f", 6, "g", 7, "h", 8, "i", 9, "j", 10, "k", 11, '
    '"l", 12)',
    "byte_limit": 'EVALUATE ADDCOLUMNS(GENERATESERIES(1, 90000), "a", REPT("x", 400))',
}


class RecordingTransport(httpx.BaseTransport):
    """Passes requests on and keeps every query with its response."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self.exchanges: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        response.read()
        self.exchanges.append(
            {
                "dataset": request.url.path.split("/")[-2],
                "query": json.loads(request.content)["queries"][0]["query"],
                "status": response.status_code,
                "body": _trimmed(response.json()),
            }
        )
        return response


def _trimmed(body: dict[str, Any]) -> dict[str, Any]:
    """Drop the partial rows of a failed result, which can reach 15 MB."""
    for result in body.get("results", []):
        if "error" in result:
            for table in result.get("tables", []):
                table["rows"] = table["rows"][:KEPT_ROWS_OF_FAILED_RESULT]
    return body


def _scrubbed(exchanges: list[dict[str, Any]], renames: dict[str, str]) -> str:
    text = json.dumps({"exchanges": exchanges}, indent=2, ensure_ascii=False)
    for real, placeholder in renames.items():
        text = text.replace(real, placeholder)
    left = set(GUID.findall(text)) - {*renames.values(), UNKNOWN_DATASET}
    if left:
        raise ValueError(f"{len(left)} unknown ids left in the recording")
    return text + "\n"


def _client(transport: RecordingTransport) -> PowerBIClient:
    tokens = MsalTokenProvider(load_powerbi_config(os.environ))
    http = httpx.Client(
        base_url=API_BASE_URL, timeout=DEFAULT_TIMEOUT_SECONDS, transport=transport
    )
    return PowerBIClient(http, tokens)


def main(old_dataset: str, new_dataset: str) -> None:
    """Write ``sales_v1_v2.json`` and ``api_behaviour.json``."""
    renames = {old_dataset: OLD_PLACEHOLDER, new_dataset: NEW_PLACEHOLDER}
    settings = DataSettings(old_dataset=old_dataset, new_dataset=new_dataset)

    transport = RecordingTransport()
    validate(ROOT / "sales_v1", ROOT / "sales_v2", settings, _client(transport))
    RECORDED.mkdir(exist_ok=True)
    path = RECORDED / "sales_v1_v2.json"
    path.write_text(_scrubbed(transport.exchanges, renames), encoding="utf-8")

    transport = RecordingTransport()
    client = _client(transport)
    for dax in ERROR_QUERIES.values():
        _run_ignoring_query_errors(client, old_dataset, dax)
    _run_ignoring_query_errors(client, UNKNOWN_DATASET, 'EVALUATE ROW("x", 1)')
    for exchange, name in zip(
        transport.exchanges, [*ERROR_QUERIES, "unknown_dataset"], strict=True
    ):
        exchange["name"] = name
    path = RECORDED / "api_behaviour.json"
    path.write_text(_scrubbed(transport.exchanges, renames), encoding="utf-8")


def _run_ignoring_query_errors(client: PowerBIClient, dataset: str, dax: str) -> None:
    with contextlib.suppress(PowerBIError):
        client.execute_query(dataset, dax)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
