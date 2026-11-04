from typer.testing import CliRunner

from pbi_report_validator.cli.main import EXIT_USAGE, app
from pbi_report_validator.domain.models import (
    Attribution,
    DataSettings,
    DataStatus,
    DataSummary,
    DiffResult,
    QueryResult,
)
from pbi_report_validator.integrations.powerbi import QueryError
from pbi_report_validator.integrations.templates import read_template
from pbi_report_validator.reporting.ai_payload import build_payload
from pbi_report_validator.reporting.html import REPORT_TEMPLATE, to_html
from pbi_report_validator.reporting.labels import ATTRIBUTION_HEADING
from pbi_report_validator.reporting.markdown import to_markdown
from pbi_report_validator.reporting.terminal import format_summary
from pbi_report_validator.services.data_validation import ENGINE_MESSAGE_MASKED
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES
from tests.services.test_data_validation import NEW_DS, OLD_DS, FakeRunner

ATTRIBUTE = DataSettings(old_dataset=OLD_DS, new_dataset=NEW_DS, attribute=True)
CHART = "overview/chart_sales_by_month"
VISUALS = 5


class ReportChangeRunner(FakeRunner):
    """Gives the new numbers to the new report's query on either dataset."""

    def __init__(self, fail_cross: bool = False) -> None:
        super().__init__()
        self.new_queries: set[str] = set()
        self.fail_cross = fail_cross

    def execute_query(self, dataset_id: str, dax: str) -> QueryResult:
        if dataset_id == NEW_DS:
            self.new_queries.add(dax)
        elif dax in self.new_queries:
            if self.fail_cross:
                raise QueryError("Measure [Total Sales] not found")
            dataset_id = NEW_DS
        return super().execute_query(dataset_id, dax)


def summaries(runner: FakeRunner, settings: DataSettings = ATTRIBUTE) -> DiffResult:
    return validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2", settings, runner)


def chart(result: DiffResult) -> DataSummary:
    return next(s for s in result.data if s.path == CHART)


def test_difference_from_the_model_is_attributed_to_the_model() -> None:
    runner = FakeRunner()

    result = summaries(runner)

    assert chart(result).attribution is Attribution.MODEL
    assert chart(result).attribution_reason is None
    assert [s.attribution for s in result.data if s.path != CHART] == [None] * 4
    # Only the differing visual is queried a third time: new query, old dataset.
    datasets = [dataset for dataset, _ in runner.queries]
    assert datasets.count(OLD_DS) == VISUALS + 1
    assert datasets.count(NEW_DS) == VISUALS
    cross = [
        dax
        for i, (dataset, dax) in enumerate(runner.queries)
        if dataset == OLD_DS and (NEW_DS, dax) in runner.queries[:i]
    ]
    assert len(cross) == 1
    assert "'Date'[Month]" in cross[0]


def test_difference_from_the_report_is_attributed_to_the_report() -> None:
    result = summaries(ReportChangeRunner())

    assert chart(result).status is DataStatus.DIFFERENT
    assert chart(result).attribution is Attribution.REPORT


def test_failing_cross_query_is_unknown_with_a_masked_reason() -> None:
    result = summaries(ReportChangeRunner(fail_cross=True))

    assert chart(result).status is DataStatus.DIFFERENT
    assert chart(result).attribution is Attribution.UNKNOWN
    assert chart(result).attribution_reason == (
        f"the new report's query on the old model: query failed: "
        f"{ENGINE_MESSAGE_MASKED}"
    )


def test_without_attribute_no_extra_query_runs() -> None:
    runner = FakeRunner()
    settings = ATTRIBUTE.model_copy(update={"attribute": False})

    result = summaries(runner, settings)

    assert chart(result).attribution is None
    assert len(runner.queries) == 2 * VISUALS


def test_attribute_needs_data() -> None:
    old, new = str(FIXTURES / "sales_v1"), str(FIXTURES / "sales_v2")

    result = CliRunner().invoke(app, ["diff", old, new, "--attribute"])

    assert result.exit_code == EXIT_USAGE
    assert "--attribute needs --data" in result.output


def test_attribution_is_in_every_output() -> None:
    result = summaries(FakeRunner())

    assert result.model_dump(mode="json")["data"][4]["attribution"] == "model"
    markdown = to_markdown(result)
    assert ATTRIBUTION_HEADING in markdown
    assert f"- `{CHART}`: semantic model change" in markdown
    assert f"  {CHART}: semantic model change" in format_summary(result)
    html = to_html(result, read_template(REPORT_TEMPLATE), "test")
    assert "<dt>Cause</dt><dd>semantic model change</dd>" in html


def test_ai_payload_keeps_the_attribution_but_not_its_reason() -> None:
    summary = DataSummary(
        path=CHART,
        status=DataStatus.DIFFERENT,
        attribution=Attribution.UNKNOWN,
        attribution_reason="the report change: column [x] is missing",
    )
    result = DiffResult(old_source="a", new_source="b", data=(summary,))

    withheld = build_payload(result, allow_data=False).data[0]
    allowed = build_payload(result, allow_data=True).data[0]

    assert (withheld.attribution, withheld.attribution_reason) == (
        Attribution.UNKNOWN,
        None,
    )
    assert allowed.attribution_reason == summary.attribution_reason
