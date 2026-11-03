"""Replays responses recorded from the real API; see tests/fixtures/README.md."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from pbi_report_validator.domain.models import (
    Category,
    DataSettings,
    DataStatus,
    DiffResult,
)
from pbi_report_validator.integrations.powerbi import (
    API_BASE_URL,
    DatasetNotFoundError,
    PowerBIClient,
    PowerBIError,
    QueryError,
)
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES
from tests.record_powerbi_responses import (
    NEW_PLACEHOLDER,
    OLD_PLACEHOLDER,
    UNKNOWN_DATASET,
)

RECORDED = FIXTURES / "recorded"
SETTINGS = DataSettings(old_dataset=OLD_PLACEHOLDER, new_dataset=NEW_PLACEHOLDER)


class FakeTokens:
    def get_token(self) -> str:
        return "test-token"


def exchanges(path: Path) -> list[dict[str, Any]]:
    data: dict[str, list[dict[str, Any]]] = json.loads(path.read_text("utf-8"))
    return data["exchanges"]


def replaying(recorded: list[dict[str, Any]]) -> PowerBIClient:
    """A real client whose HTTP layer answers from the recording."""
    answers = {(e["dataset"], e["query"]): e for e in recorded}

    def handler(request: httpx.Request) -> httpx.Response:
        dataset = request.url.path.split("/")[-2]
        query = json.loads(request.content)["queries"][0]["query"]
        recording = answers.get((dataset, query))
        assert recording, f"not recorded, see tests/fixtures/README.md: {query}"
        return httpx.Response(recording["status"], json=recording["body"])

    transport = httpx.MockTransport(handler)
    http = httpx.Client(base_url=API_BASE_URL, transport=transport)
    return PowerBIClient(http, FakeTokens(), max_retries=0)


def recorded_run() -> DiffResult:
    client = replaying(exchanges(RECORDED / "sales_v1_v2.json"))
    return validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", SETTINGS, client)


def behaviour(name: str) -> tuple[PowerBIClient, str, str]:
    recorded = exchanges(RECORDED / "api_behaviour.json")
    exchange = next(e for e in recorded if e["name"] == name)
    return replaying(recorded), exchange["dataset"], exchange["query"]


def test_every_visual_of_the_sample_reports_is_compared() -> None:
    assert [(s.path, s.status) for s in recorded_run().data] == [
        ("details/chart_sales_by_region", DataStatus.SAME),
        ("details/table_product_sales", DataStatus.DIFFERENT),
        ("overview/card_margin", DataStatus.DIFFERENT),
        ("overview/card_total_sales", DataStatus.DIFFERENT),
        ("overview/chart_sales_by_month", DataStatus.DIFFERENT),
    ]


def test_slicer_change_and_removed_filter_show_as_number_differences() -> None:
    findings = [f.path for f in recorded_run().findings if f.category == Category.DATA]

    assert findings == [
        "details/table_product_sales/data/row 1",
        "overview/card_margin/data/total/[Margin %]",
        "overview/card_total_sales/data/total/[Total Sales]",
        "overview/chart_sales_by_month/data/row 1",
        "overview/chart_sales_by_month/data/row 2",
    ]


def test_recorded_totals_are_what_the_sample_data_adds_up_to() -> None:
    card = next(s for s in recorded_run().data if s.path.endswith("card_total_sales"))

    # 2025 without Accessories is 1200 + 80, and 2024 is 1100.
    assert card.max_abs_delta == 180.0


def test_empty_result_has_no_columns() -> None:
    client, dataset, query = behaviour("empty_result")

    result = client.execute_query(dataset, query)

    assert result.columns == ()
    assert result.rows == ()


def test_values_keep_their_type_and_dates_are_text() -> None:
    client, dataset, query = behaviour("value_types")

    result = client.execute_query(dataset, query)

    assert result.rows == ((1, 0.1, True, "2025-01-15T00:00:00", None),)


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("unknown_table", QueryError, "Query (1, 19) Cannot find table 'Nope'."),
        ("syntax_error", QueryError, "The syntax for 'THIS' is incorrect"),
        ("runtime_error", QueryError, "Query (1, 19) boom"),
        ("row_limit", QueryError, "Only 100000 rows are allowed"),
        ("value_limit", QueryError, "Only 76923 rows are allowed"),
        ("byte_limit", QueryError, "Only 15728640 bytes are allowed"),
        ("unknown_dataset", DatasetNotFoundError, "PowerBIEntityNotFound"),
    ],
)
def test_recorded_errors_keep_their_message(
    name: str, error: type[PowerBIError], message: str
) -> None:
    client, dataset, query = behaviour(name)

    with pytest.raises(error) as caught:
        client.execute_query(dataset, query)

    assert message in str(caught.value)


def test_recordings_contain_only_placeholder_datasets() -> None:
    used = {
        exchange["dataset"]
        for name in ("sales_v1_v2.json", "api_behaviour.json")
        for exchange in exchanges(RECORDED / name)
    }

    assert used == {OLD_PLACEHOLDER, NEW_PLACEHOLDER, UNKNOWN_DATASET}
