from pathlib import Path

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.integrations.templates import TemplateNotFoundError
from tests.factories import REPO_ROOT, SNAPSHOTS

SNAPSHOT = SNAPSHOTS / "diff_sales_v1_v2.json"
OLD = "tests/fixtures/sales_v1"
NEW = "tests/fixtures/sales_v2"

runner = CliRunner()


@pytest.fixture(autouse=True)
def run_from_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)


def test_diff_prints_summary() -> None:
    result = runner.invoke(app, ["diff", OLD, NEW])

    assert result.exit_code == 0
    assert "7 findings (3 critical, 2 warning, 2 info):" in result.stdout
    assert "[added] trends: Page 'Trends' added with 1 visual" in result.stdout


def test_diff_json_matches_snapshot_and_is_stable(tmp_path: Path) -> None:
    # old_source/new_source are the paths as given, so the snapshot only
    # matches when run from the repo root (see run_from_repo_root).
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


def test_report_folder_can_be_passed_directly() -> None:
    result = runner.invoke(app, ["diff", f"{OLD}/Sales.Report", f"{NEW}/Sales.Report"])

    assert result.exit_code == 0
    assert "7 findings (3 critical, 2 warning, 2 info):" in result.stdout


def test_verbose_logs_progress(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO"):
        result = runner.invoke(app, ["diff", OLD, NEW, "--verbose"])

    assert result.exit_code == 0
    assert "Found 7 findings" in caplog.text


def test_diff_markdown_matches_snapshot(tmp_path: Path) -> None:
    # Update with: uv run pbi-validate diff tests/fixtures/sales_v1
    #   tests/fixtures/sales_v2 --markdown tests/snapshots/diff_sales_v1_v2.md
    target = tmp_path / "diff.md"

    result = runner.invoke(app, ["diff", OLD, NEW, "--markdown", str(target)])

    assert result.exit_code == 0
    assert "Markdown written to" in result.stdout
    expected = SNAPSHOTS / "diff_sales_v1_v2.md"
    assert target.read_bytes() == expected.read_bytes()


def test_json_and_markdown_together(tmp_path: Path) -> None:
    json_file, md_file = tmp_path / "d.json", tmp_path / "d.md"

    result = runner.invoke(
        app, ["diff", OLD, NEW, "--json", str(json_file), "--markdown", str(md_file)]
    )

    assert result.exit_code == 0
    assert json_file.exists() and md_file.exists()
    assert "JSON written to" in result.stdout
    assert "Markdown written to" in result.stdout


def test_diff_writes_html_report(tmp_path: Path) -> None:
    target = tmp_path / "report.html"

    result = runner.invoke(app, ["diff", OLD, NEW, "--html", str(target)])

    assert result.exit_code == 0
    assert "HTML written to" in result.stdout
    assert target.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_missing_html_template_exits_with_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(name: str) -> str:
        raise TemplateNotFoundError(f"template {name} not found")

    monkeypatch.setattr("pbi_report_validator.services.validate.read_template", missing)

    result = runner.invoke(app, ["diff", OLD, NEW, "--html", str(tmp_path / "r.html")])

    assert result.exit_code == 1
    assert "Error: template report.html.j2 not found" in result.stderr
