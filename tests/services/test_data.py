import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.diff.data import compare_results
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataStatus,
    QueryResult,
)
from pbi_report_validator.integrations.powerbi import (
    AuthenticationError,
    InvalidDatasetIdError,
    QueryError,
    RateLimitError,
)
from pbi_report_validator.integrations.templates import read_template
from pbi_report_validator.reporting.html import REPORT_TEMPLATE, to_html
from pbi_report_validator.reporting.markdown import to_markdown
from pbi_report_validator.reporting.terminal import format_summary
from pbi_report_validator.services.data import (
    DataRun,
    DataSettings,
    InvalidDataOptionsError,
    _with_unpaired,
    data_settings,
    result_column,
)
from pbi_report_validator.services.validate import validate

FIXTURES = Path(__file__).parent.parent / "fixtures"
REPO_ROOT = Path(__file__).parent.parent.parent
OLD_DS = "11111111-1111-1111-1111-111111111111"
NEW_DS = "22222222-2222-2222-2222-222222222222"
SETTINGS = DataSettings(old_dataset=OLD_DS, new_dataset=NEW_DS)
KEY_VALUES = {
    "Date[Month]": ["2025-01", "2025-02"],
    "Sales[Region]": ["North", "South"],
    "Product[Category]": ["Bikes", "Clothing"],
    "Product[Product]": ["Road Bike", "Jersey"],
}


class FakeRunner:
    """Answers generated queries with plausible rows.

    Every value is 100, except Total Sales for 2025-02 in the new dataset
    (120), which simulates the changed Total Sales expression.
    """

    def __init__(self, fail_on: str | None = None) -> None:
        self.queries: list[tuple[str, str]] = []
        self.fail_on = fail_on

    def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
        self.queries.append((dataset_id, dax))
        if self.fail_on and self.fail_on in dax:
            raise QueryError("Column not found")
        keys = [
            result_column(line.strip().removesuffix(","))
            for line in dax.splitlines()
            if re.fullmatch(r"\s+'[^']+'\[[^\]]+\],?", line)
        ]
        names = re.findall(r'"([^"]+)", ', dax)
        columns = (*keys, *(f"[{n}]" for n in names))
        rows = []
        for index in range(2 if keys else 1):
            key = [KEY_VALUES[k][index] for k in keys]
            values = [
                120.0
                if dataset_id == NEW_DS and n == "Total Sales" and "2025-02" in key
                else 100.0
                for n in names
            ]
            rows.append((*key, *values))
        return QueryResult(columns=columns, rows=tuple(rows))


def run(runner: FakeRunner) -> tuple[list[tuple[str, DataStatus]], list[str]]:
    result = validate(
        FIXTURES / "sales_v1", FIXTURES / "sales_v2", DataRun(SETTINGS, runner)
    )
    data = [f.path for f in result.findings if f.category == Category.DATA]
    return [(s.path, s.status) for s in result.data], data


def test_fixture_pair_compares_every_non_slicer_visual() -> None:
    summaries, data_findings = run(FakeRunner())

    assert summaries == [
        ("details/chart_sales_by_region", DataStatus.SAME),
        ("details/table_product_sales", DataStatus.SAME),
        ("overview/card_margin", DataStatus.SAME),
        ("overview/card_total_sales", DataStatus.SAME),
        ("overview/chart_sales_by_month", DataStatus.DIFFERENT),
    ]
    assert data_findings == [
        "overview/chart_sales_by_month/data/Date[Month]=2025-02/[Total Sales]"
    ]


def test_queries_go_to_the_right_dataset_and_use_new_measure_names() -> None:
    runner = FakeRunner()
    run(runner)

    assert len(runner.queries) == 10
    new_queries = [dax for ds, dax in runner.queries if ds == NEW_DS]
    assert any("[Gross Margin %]" in q for q in new_queries)
    assert not any("[Margin %]" in q for ds, q in runner.queries if ds == NEW_DS)


def test_failed_query_is_not_validated_and_run_continues() -> None:
    summaries, data_findings = run(FakeRunner(fail_on="'Sales'[Region]"))

    statuses = dict(summaries)
    assert statuses["details/chart_sales_by_region"] == DataStatus.NOT_VALIDATED
    assert statuses["overview/chart_sales_by_month"] == DataStatus.DIFFERENT
    assert "details/chart_sales_by_region/data" in data_findings


def test_without_data_settings_nothing_is_queried() -> None:
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2")

    assert result.data == ()
    assert not any(f.category == Category.DATA for f in result.findings)


def test_reports_show_data_results() -> None:
    result = validate(
        FIXTURES / "sales_v1", FIXTURES / "sales_v2", DataRun(SETTINGS, FakeRunner())
    )
    overview = "Data: 5 visuals compared, 4 same, 1 different, 0 not validated"

    assert overview in format_summary(result)
    markdown = to_markdown(result)
    assert overview in markdown
    assert "### Data" in markdown
    html = to_html(result, read_template(REPORT_TEMPLATE), "test")
    assert overview in html
    assert "different: 2 rows matched, 1 differing, 0 only old, 0 only new" in html
    finding = next(f for f in result.findings if f.category == Category.DATA)
    assert (finding.change, finding.old, finding.new) == (
        ChangeKind.MODIFIED,
        "100",
        "120",
    )


cli = CliRunner()


@pytest.fixture
def repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


def test_cli_data_needs_both_datasets(repo_root: None) -> None:
    result = cli.invoke(
        app, ["diff", "tests/fixtures/sales_v1", "tests/fixtures/sales_v2", "--data"]
    )

    assert result.exit_code == 2
    assert "Error: --data needs --old-dataset and --new-dataset" in result.stderr


def test_cli_data_without_credentials_names_the_variables(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("PBI_TENANT_ID", "PBI_CLIENT_ID", "PBI_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)

    result = cli.invoke(
        app,
        [
            "diff",
            "tests/fixtures/sales_v1",
            "tests/fixtures/sales_v2",
            "--data",
            "--old-dataset",
            OLD_DS,
            "--new-dataset",
            NEW_DS,
        ],
    )

    assert result.exit_code == 1
    assert "PBI_TENANT_ID, PBI_CLIENT_ID, PBI_CLIENT_SECRET" in result.stderr


def test_cli_runs_data_validation_with_tolerance(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner", lambda env: FakeRunner()
    )

    result = cli.invoke(
        app,
        [
            "diff",
            "tests/fixtures/sales_v1",
            "tests/fixtures/sales_v2",
            "--data",
            "--old-dataset",
            OLD_DS,
            "--new-dataset",
            NEW_DS,
            "--abs-tol",
            "25",
        ],
    )

    assert result.exit_code == 0
    assert (
        "Data: 5 visuals compared, 5 same, 0 different, 0 not validated"
        in result.stdout
    )


def test_cli_authentication_failure_exits_with_error(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Denied(FakeRunner):
        def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
            raise AuthenticationError("could not sign in to Power BI: bad secret")

    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner", lambda env: Denied()
    )

    result = cli.invoke(
        app,
        [
            "diff",
            "tests/fixtures/sales_v1",
            "tests/fixtures/sales_v2",
            "--data",
            "--old-dataset",
            OLD_DS,
            "--new-dataset",
            NEW_DS,
        ],
    )

    assert result.exit_code == 1
    assert "could not sign in to Power BI: bad secret" in result.stderr


@pytest.mark.parametrize(
    ("reference", "expected"),
    [("'Date'[Month]", "Date[Month]"), ("'Bob''s Orders'[Net]", "Bob's Orders[Net]")],
)
def test_result_column(reference: str, expected: str) -> None:
    assert result_column(reference) == expected


def test_measure_only_in_one_version_is_noted_not_hidden() -> None:
    data = QueryResult(columns=("[A]",), rows=((1,),))
    comparison = compare_results("p/v", data, data, [], [("[A]", "[A]")])

    noted = _with_unpaired(comparison, "p/v", ["Margin"], ["Profit"])

    assert noted.summary.status == DataStatus.SAME
    assert noted.summary.reason == (
        "not compared: [Margin] is only in the old visual; "
        "[Profit] is only in the new visual"
    )
    assert noted.findings[-1].change == ChangeKind.ERROR


def test_rate_limited_query_is_not_validated() -> None:
    class Limited(FakeRunner):
        def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
            raise RateLimitError("Power BI API rate limit reached")

    summaries, _ = run(Limited())

    assert {status for _, status in summaries} == {DataStatus.NOT_VALIDATED}


def test_data_settings_require_both_datasets() -> None:
    with pytest.raises(InvalidDataOptionsError):
        data_settings(OLD_DS, None)
    settings = data_settings(OLD_DS, NEW_DS, 0.5, 0.01)
    assert (settings.tolerance.absolute, settings.tolerance.relative) == (0.5, 0.01)


def test_cli_invalid_dataset_id_exits_with_error(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BadId(FakeRunner):
        def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
            raise InvalidDatasetIdError(
                f"dataset id must be a GUID, got {dataset_id!r}"
            )

    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner", lambda env: BadId()
    )

    result = cli.invoke(
        app,
        [
            "diff",
            "tests/fixtures/sales_v1",
            "tests/fixtures/sales_v2",
            "--data",
            "--old-dataset",
            "not-a-guid",
            "--new-dataset",
            NEW_DS,
        ],
    )

    assert result.exit_code == 1
    assert "dataset id must be a GUID" in result.stderr
