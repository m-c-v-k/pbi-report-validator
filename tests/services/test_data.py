import logging
import re

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.dax.builder import result_column
from pbi_report_validator.diff.data import compare_results, not_fully_validated
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DataSettings,
    DataStatus,
    DaxQuery,
    QueryResult,
    Severity,
    UnsupportedQuery,
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
    InvalidDataOptionsError,
    _comparable_queries,
    _pair_values,
    _with_unpaired,
    data_settings,
)
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, REPO_ROOT

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
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", SETTINGS, runner)
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
    assert data_findings == ["overview/chart_sales_by_month/data/row 2/[Total Sales]"]


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
        FIXTURES / "sales_v1", FIXTURES / "sales_v2", SETTINGS, FakeRunner()
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
        "(masked)",
        "(masked)",
    )
    assert not result.data_values_shown
    assert "nmasked data" not in markdown and "nmasked data" not in html


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


def test_data_findings_get_a_severity() -> None:
    runner = FakeRunner(fail_on="'Sales'[Region]")
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", SETTINGS, runner)

    severities = {
        (f.change, f.severity) for f in result.findings if f.category == Category.DATA
    }
    assert severities == {
        (ChangeKind.MODIFIED, Severity.CRITICAL),
        (ChangeKind.ERROR, Severity.WARNING),
    }


DATA_ARGS = [
    "diff",
    "tests/fixtures/sales_v1",
    "tests/fixtures/sales_v2",
    "--data",
    "--old-dataset",
    OLD_DS,
    "--new-dataset",
    NEW_DS,
]


def test_fail_on_data_error_passes_when_all_data_is_validated(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner", lambda env: FakeRunner()
    )

    result = cli.invoke(app, [*DATA_ARGS, "--fail-on-data-error"])

    assert result.exit_code == 0
    assert "Failed:" not in result.stderr


def test_fail_on_data_error_fails_on_a_failed_query(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner",
        lambda env: FakeRunner(fail_on="'Sales'[Region]"),
    )

    result = cli.invoke(app, [*DATA_ARGS, "--fail-on-data-error"])

    assert result.exit_code == 3
    assert re.search(
        r"Failed: data of \d+ visuals? not fully validated \(--fail-on-data-error\)",
        result.stderr,
    )


def test_fail_on_and_fail_on_data_error_both_report(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner",
        lambda env: FakeRunner(fail_on="'Sales'[Region]"),
    )

    both = cli.invoke(
        app, [*DATA_ARGS, "--fail-on", "critical", "--fail-on-data-error"]
    )

    assert both.exit_code == 3
    assert "(--fail-on critical)" in both.stderr
    assert "(--fail-on-data-error)" in both.stderr


def test_fail_on_data_error_needs_data(repo_root: None) -> None:
    result = cli.invoke(
        app,
        [*DATA_ARGS[:3], "--fail-on-data-error"],
    )

    assert result.exit_code == 2
    assert "--fail-on-data-error needs --data" in result.stderr


def test_not_fully_validated_selects_data_errors() -> None:
    runner = FakeRunner(fail_on="'Sales'[Region]")
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", SETTINGS, runner)

    unchecked = not_fully_validated(result.findings)

    assert unchecked
    assert {(f.category, f.change) for f in unchecked} == {
        (Category.DATA, ChangeKind.ERROR)
    }
    not_validated = [s for s in result.data if s.status == DataStatus.NOT_VALIDATED]
    assert len(unchecked) >= len(not_validated)


def test_show_values_puts_values_in_reports_with_a_warning() -> None:
    settings = SETTINGS.model_copy(update={"show_values": True})

    result = validate(
        FIXTURES / "sales_v1", FIXTURES / "sales_v2", settings, FakeRunner()
    )

    finding = next(f for f in result.findings if f.category == Category.DATA)
    assert (finding.path, finding.old, finding.new) == (
        "overview/chart_sales_by_month/data/Date[Month]=2025-02/[Total Sales]",
        "100",
        "120",
    )
    assert result.data_values_shown
    assert to_markdown(result).startswith("> [!WARNING]")
    assert 'role="alert"' in to_html(result, read_template(REPORT_TEMPLATE), "test")


def test_cli_show_data_values_needs_data(repo_root: None) -> None:
    result = cli.invoke(
        app,
        [
            "diff",
            "tests/fixtures/sales_v1",
            "tests/fixtures/sales_v2",
            "--show-data-values",
        ],
    )

    assert result.exit_code == 2
    assert "--show-data-values needs --data" in result.stderr


def test_cli_show_data_values_warns_on_stderr(
    repo_root: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.create_runner", lambda env: FakeRunner()
    )
    args = ["diff", "tests/fixtures/sales_v1", "tests/fixtures/sales_v2", "--data"]
    args += ["--old-dataset", OLD_DS, "--new-dataset", NEW_DS]

    masked = cli.invoke(app, args)
    shown = cli.invoke(app, [*args, "--show-data-values"])

    assert "UNMASKED DATA" not in masked.stderr
    assert "Date[Month]=2025-02" not in masked.stdout
    assert "WARNING: UNMASKED DATA" in shown.stderr
    assert "Date[Month]=2025-02" in shown.stdout


BY_MONTH = DaxQuery(dax="q1", group_by=("'Date'[Month]",), values=("Sales",))
BY_YEAR = DaxQuery(dax="q2", group_by=("'Date'[Year]",), values=("Sales",))
UNSUPPORTED = UnsupportedQuery(reason="visual type map is not supported")


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        (UNSUPPORTED, BY_MONTH, "visual type map is not supported"),
        (BY_MONTH, UNSUPPORTED, "visual type map is not supported"),
        (BY_MONTH, BY_YEAR, "the visual is grouped by different columns"),
        (BY_MONTH, BY_MONTH, (BY_MONTH, BY_MONTH)),
    ],
)
def test_comparable_queries(
    old: DaxQuery | UnsupportedQuery,
    new: DaxQuery | UnsupportedQuery,
    expected: tuple[DaxQuery, DaxQuery] | str,
) -> None:
    assert _comparable_queries(old, new) == expected


def test_pair_values_follows_renames_and_lists_unpaired() -> None:
    pairs = _pair_values(
        ("Margin %", "Sales", "Old only"),
        ("Gross Margin %", "Sales", "New only"),
        {"Margin %": "Gross Margin %"},
    )

    assert pairs.columns == (("[Margin %]", "[Gross Margin %]"), ("[Sales]", "[Sales]"))
    assert (pairs.only_old, pairs.only_new) == (("Old only",), ("New only",))


# Typer's own min=0 check already rejects -inf; nan and inf reach Tolerance.
@pytest.mark.parametrize(
    ("value", "message"), [("nan", "finite"), ("inf", "finite"), ("-inf", "x>=0")]
)
def test_non_finite_tolerance_is_a_usage_error(
    repo_root: None, value: str, message: str
) -> None:
    with pytest.raises(InvalidDataOptionsError):
        data_settings(OLD_DS, NEW_DS, float(value), 1e-9)

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
            value,
        ],
    )

    assert result.exit_code == 2
    assert message in result.stderr


@pytest.mark.parametrize("show_values", [False, True])
def test_engine_message_of_a_failed_query_is_masked(show_values: bool) -> None:
    settings = SETTINGS.model_copy(update={"show_values": show_values})

    result = validate(
        FIXTURES / "sales_v1",
        FIXTURES / "sales_v2",
        settings,
        FakeRunner(fail_on="'Sales'[Region]"),
    )

    reason = next(s.reason for s in result.data if s.reason)
    assert ("Column not found" in reason) is show_values


def test_verbose_logging_keeps_httpx_quiet(repo_root: None) -> None:
    cli.invoke(
        app, ["diff", "tests/fixtures/sales_v1", "tests/fixtures/sales_v2", "-v"]
    )

    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING
