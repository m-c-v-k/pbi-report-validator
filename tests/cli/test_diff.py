from pathlib import Path

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app

REPO_ROOT = Path(__file__).parent.parent.parent
SNAPSHOT = REPO_ROOT / "tests/snapshots/diff_sales_v1_v2.json"
OLD = "tests/fixtures/sales_v1"
NEW = "tests/fixtures/sales_v2"

runner = CliRunner()


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


def test_diff_prints_summary() -> None:
    result = runner.invoke(app, ["diff", OLD, NEW])

    assert result.exit_code == 0
    assert "7 findings:" in result.stdout
    assert "[added] trends: Page 'Trends' added with 1 visual" in result.stdout


def test_diff_json_matches_snapshot_and_is_stable(tmp_path: Path) -> None:
    # To update after an intended change:
    # uv run pbi-validate diff tests/fixtures/sales_v1 tests/fixtures/sales_v2 \
    #   --json tests/snapshots/diff_sales_v1_v2.json
    first, second = tmp_path / "a.json", tmp_path / "b.json"

    for target in (first, second):
        result = runner.invoke(app, ["diff", OLD, NEW, "--json", str(target)])
        assert result.exit_code == 0

    assert first.read_bytes() == second.read_bytes() == SNAPSHOT.read_bytes()


def test_identical_versions_report_no_differences() -> None:
    result = runner.invoke(app, ["diff", OLD, OLD])

    assert result.exit_code == 0
    assert "No differences found." in result.stdout


def test_missing_project_exits_with_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", str(tmp_path / "nope"), NEW])

    assert result.exit_code == 1
    assert "Error:" in result.stderr


def test_unwritable_json_path_exits_with_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("")

    result = runner.invoke(app, ["diff", OLD, NEW, "--json", str(blocker / "x.json")])

    assert result.exit_code == 1
    assert "could not write" in result.stderr


def test_works_without_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "PBI_TENANT_ID",
        "PBI_CLIENT_ID",
        "PBI_CLIENT_SECRET",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    assert runner.invoke(app, ["diff", OLD, NEW]).exit_code == 0
