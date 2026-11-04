import json
import shutil
from pathlib import Path

from pbi_report_validator.domain.models import Category, ChangeKind, DataStatus
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES
from tests.services.test_data_validation import SETTINGS, FakeRunner

# A synthetic connection string: no real workspace or dataset.
BY_CONNECTION = {
    "datasetReference": {
        "byConnection": {"connectionString": "Data Source=powerbi://example;"}
    }
}


def published(tmp_path: Path, fixture: str) -> Path:
    """A copy of ``fixture`` whose report is connected to a published model."""
    target = shutil.copytree(FIXTURES / fixture, tmp_path / fixture)
    pbir = target / "Sales.Report" / "definition.pbir"
    pbir.write_text(json.dumps(BY_CONNECTION), encoding="utf-8")
    return target


def test_by_connection_reports_compare_their_sibling_models(tmp_path: Path) -> None:
    old, new = published(tmp_path, "sales_v1"), published(tmp_path, "sales_v2")

    result = validate(old, new, SETTINGS, FakeRunner())

    measures = [
        (f.change, f.path) for f in result.findings if f.category is Category.MEASURE
    ]
    assert measures == [
        (ChangeKind.RENAMED, "model/Sales/Margin %"),
        (ChangeKind.MODIFIED, "model/Sales/Total Sales"),
    ]
    assert not [f for f in result.findings if f.category is Category.PARSE_ISSUE]
    card = next(s for s in result.data if s.path == "overview/card_margin")
    assert card.status is DataStatus.SAME


def test_by_connection_gives_the_same_result_as_by_path(tmp_path: Path) -> None:
    old, new = published(tmp_path, "sales_v1"), published(tmp_path, "sales_v2")

    by_connection = validate(old, new).findings
    by_path = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2").findings

    assert [f.model_dump() for f in by_connection] == [f.model_dump() for f in by_path]
