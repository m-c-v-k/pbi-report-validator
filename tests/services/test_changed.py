"""``pbi-validate changed``: tested against git repositories built from fixtures."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.domain.models import (
    ChangedResult,
    DiffResult,
    ProjectStatus,
    Severity,
)
from pbi_report_validator.integrations.git import (
    NotARepositoryError,
    UnknownRefError,
)
from pbi_report_validator.reporting.json_out import to_json
from pbi_report_validator.services.changed import run_failures, validate_changed
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, SNAPSHOTS
from tests.pbit import write_pbit

SALES = "reports/sales"
REPORT = f"{SALES}/Sales.Report"
MEASURES = "Sales.SemanticModel/definition/tables/Sales.tmdl"

runner = CliRunner()


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def commit(repo: Path, message: str = "change") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def put(repo: Path, fixture: str, target: str = SALES) -> None:
    """Make ``target`` in the working tree a copy of a fixture project."""
    shutil.rmtree(repo / target, ignore_errors=True)
    shutil.copytree(FIXTURES / fixture, repo / target)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository whose ``base`` tag has sales_v1 in ``reports/sales``."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    put(root, "sales_v1")
    (root / "README.md").write_text("reports\n", encoding="utf-8")
    commit(root, "base")
    git(root, "tag", "base")
    return root


def findings(result: DiffResult | None) -> list[tuple[str, str, str]]:
    assert result is not None
    return [(f.category, f.change, f.path) for f in result.findings]


def test_nothing_changed(repo: Path) -> None:
    (repo / "README.md").write_text("other\n", encoding="utf-8")

    assert validate_changed(repo, "base").projects == ()


def test_changed_report_is_compared_with_its_base_version(repo: Path) -> None:
    put(repo, "sales_v2")

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == (REPORT, ProjectStatus.CHANGED)
    expected = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2")
    assert findings(run.result) == findings(expected)
    assert run.result is not None
    assert run.result.old_source == f"base:{REPORT}"
    assert run.result.new_source == REPORT


def test_committed_changes_count_too(repo: Path) -> None:
    put(repo, "sales_v2")
    commit(repo)

    (run,) = validate_changed(repo, "base").projects

    assert run.status is ProjectStatus.CHANGED


def test_model_change_validates_the_report_that_reads_it(repo: Path) -> None:
    model = repo / SALES / MEASURES
    shutil.copy(FIXTURES / "sales_v2" / MEASURES, model)

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == (REPORT, ProjectStatus.CHANGED)
    assert "measure" in {category for category, *_ in findings(run.result)}


def test_model_nobody_reads_is_skipped(repo: Path) -> None:
    shutil.copytree(
        FIXTURES / "sales_v1/Sales.SemanticModel", repo / "models/Sales.SemanticModel"
    )
    commit(repo)
    git(repo, "tag", "-f", "base")
    shutil.copy(FIXTURES / "sales_v2" / MEASURES, repo / "models" / MEASURES)

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == (
        "models/Sales.SemanticModel",
        ProjectStatus.SKIPPED,
    )
    assert run.message is not None
    assert "no report in the repository reads it" in run.message


def test_added_and_removed_projects(repo: Path) -> None:
    put(repo, "sales_v1", "reports/other")
    shutil.rmtree(repo / SALES)

    result = validate_changed(repo, "base")

    assert [(r.path, r.status) for r in result.projects] == [
        ("reports/other/Sales.Report", ProjectStatus.ADDED),
        (REPORT, ProjectStatus.REMOVED),
    ]
    assert run_failures(result, Severity.CRITICAL) == [f"{REPORT}: project removed"]
    assert len(run_failures(result, Severity.INFO)) == 2
    assert run_failures(result, None) == []


def test_changed_pbit_is_compared(repo: Path) -> None:
    (repo / "templates").mkdir()
    write_pbit(FIXTURES / "sales_v1_legacy", repo / "templates/Sales.pbit")
    commit(repo)
    git(repo, "tag", "-f", "base")
    write_pbit(FIXTURES / "sales_v2_legacy", repo / "templates/Sales.pbit")

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == ("templates/Sales.pbit", ProjectStatus.CHANGED)
    expected = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2")
    assert findings(run.result) == findings(expected)


def test_only_changes_under_the_given_folder_count(repo: Path) -> None:
    put(repo, "sales_v2")
    (repo / "docs").mkdir()

    assert validate_changed(repo / "docs", "base").projects == ()
    assert len(validate_changed(repo / "reports", "base").projects) == 1


def test_project_that_cannot_be_loaded_is_an_error_run(repo: Path) -> None:
    (repo / REPORT / "definition/report.json").write_text("{", encoding="utf-8")

    (run,) = validate_changed(repo, "base").projects

    assert run.status is ProjectStatus.ERROR
    assert run.message is not None
    assert "invalid JSON" in run.message


def test_unknown_ref_explains_how_to_fetch(repo: Path) -> None:
    with pytest.raises(UnknownRefError, match="git fetch origin missing"):
        validate_changed(repo, "missing")


def test_ref_that_looks_like_an_option_is_refused(repo: Path) -> None:
    with pytest.raises(UnknownRefError):
        validate_changed(repo, "--output=x")


def test_base_missing_from_a_shallow_clone(repo: Path, tmp_path: Path) -> None:
    put(repo, "sales_v2")
    commit(repo)
    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", "--depth", "1", repo.as_uri(), str(clone))

    with pytest.raises(UnknownRefError, match="fetch-depth: 0"):
        validate_changed(clone, "HEAD~1")


def test_folder_outside_a_repository(tmp_path: Path) -> None:
    outside = tmp_path / "plain"
    outside.mkdir()

    with pytest.raises(NotARepositoryError):
        validate_changed(outside, "base")


def test_cli_exit_codes(repo: Path) -> None:
    put(repo, "sales_v2")
    args = ["changed", "--base", "base", str(repo)]

    passed = runner.invoke(app, args)
    failed = runner.invoke(app, [*args, "--fail-on", "critical"])

    assert passed.exit_code == 0, passed.stderr
    assert "1 project changed since base" in passed.stdout
    assert f"== {REPORT} (changed)" in passed.stdout
    assert failed.exit_code == 3
    assert f"Failed: {REPORT}: Failed:" not in failed.stderr
    assert REPORT in failed.stderr


def test_cli_error_run_exits_with_1(repo: Path) -> None:
    (repo / REPORT / "definition/report.json").write_text("{", encoding="utf-8")

    result = runner.invoke(app, ["changed", "--base", "base", str(repo)])

    assert result.exit_code == 1
    assert "(error)" in result.stdout


def test_cli_unknown_ref_exits_with_1(repo: Path) -> None:
    result = runner.invoke(app, ["changed", "--base", "missing", str(repo)])

    assert result.exit_code == 1
    assert "not available locally" in result.stderr


def test_cli_without_changes(repo: Path) -> None:
    result = runner.invoke(app, ["changed", "--base", "base", str(repo)])

    assert result.exit_code == 0
    assert "No reports or semantic models changed since base." in result.stdout


def test_project_at_the_repository_root(tmp_path: Path) -> None:
    root = tmp_path / "flat"
    shutil.copytree(FIXTURES / "sales_v1", root)
    git(root, "init", "-q")
    commit(root, "base")
    shutil.rmtree(root / "Sales.Report")
    shutil.copytree(FIXTURES / "sales_v2/Sales.Report", root / "Sales.Report")

    (run,) = validate_changed(root, "HEAD").projects

    assert (run.path, run.status) == ("Sales.Report", ProjectStatus.CHANGED)


def missing_model(result: DiffResult | None, side: str) -> bool:
    """Whether ``side`` of the comparison had no semantic model to read."""
    return any(
        category == "parse_issue" and path.startswith(f"{side}/")
        for category, _, path in findings(result)
    )


def move_model(repo: Path, folder: str) -> str:
    """Move the sales model to ``folder`` in the project, commit, retag ``base``."""
    model = f"{SALES}/{folder}/Sales.SemanticModel"
    shutil.move(repo / SALES / "Sales.SemanticModel", repo / model)
    pbir = {
        "datasetReference": {"byPath": {"path": f"../{folder}/Sales.SemanticModel"}}
    }
    (repo / REPORT / "definition.pbir").write_text(json.dumps(pbir), encoding="utf-8")
    commit(repo)
    git(repo, "tag", "-f", "base")
    return model


def test_model_in_another_folder_of_the_project(repo: Path) -> None:
    model = move_model(repo, "models")
    shutil.copy(FIXTURES / "sales_v2" / MEASURES, repo / SALES / "models" / MEASURES)

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == (REPORT, ProjectStatus.CHANGED)
    assert not missing_model(run.result, "old")
    assert "measure" in {category for category, *_ in findings(run.result)}
    assert model.startswith(SALES)


def test_model_outside_the_project_is_an_error_run(repo: Path) -> None:
    shutil.move(repo / SALES / "Sales.SemanticModel", repo / "Sales.SemanticModel")
    pbir = {"datasetReference": {"byPath": {"path": "../../../Sales.SemanticModel"}}}
    (repo / REPORT / "definition.pbir").write_text(json.dumps(pbir), encoding="utf-8")

    runs = validate_changed(repo, "base").projects

    statuses = {run.path: run.status for run in runs}
    assert statuses[REPORT] is ProjectStatus.ERROR


def test_removed_model_brings_in_the_unchanged_report_that_read_it(
    repo: Path,
) -> None:
    shutil.rmtree(repo / SALES / "Sales.SemanticModel")

    (run,) = validate_changed(repo, "base").projects

    assert (run.path, run.status) == (REPORT, ProjectStatus.CHANGED)
    assert not missing_model(run.result, "old")
    assert missing_model(run.result, "new")


def test_removed_model_nobody_reads_is_not_listed(repo: Path) -> None:
    shutil.copytree(
        FIXTURES / "sales_v1/Sales.SemanticModel", repo / "models/Sales.SemanticModel"
    )
    commit(repo)
    git(repo, "tag", "-f", "base")
    shutil.rmtree(repo / "models")

    assert validate_changed(repo, "base").projects == ()


def test_cli_error_run_exits_with_1_even_with_fail_on(repo: Path) -> None:
    put(repo, "sales_v2", "reports/other")
    (repo / REPORT / "definition/report.json").write_text("{", encoding="utf-8")

    result = runner.invoke(
        app, ["changed", "--base", "base", str(repo), "--fail-on", "info"]
    )

    assert result.exit_code == 1
    assert "(error)" in result.stdout
    assert "(added)" in result.stdout


SNAPSHOT = SNAPSHOTS / "changed_two_projects.json"


def two_project_repo(tmp_path: Path) -> Path:
    """``reports/a`` goes sales_v1 → v2, ``reports/b`` v2 → v3, ``reports/c`` is new."""
    root = tmp_path / "two"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    put(root, "sales_v1", "reports/a")
    put(root, "sales_v2", "reports/b")
    commit(root, "base")
    git(root, "tag", "base")
    put(root, "sales_v2", "reports/a")
    put(root, "sales_v3", "reports/b")
    put(root, "sales_v1", "reports/c")
    return root


def test_cli_json_for_two_projects_matches_snapshot(tmp_path: Path) -> None:
    # To update after an intended change, write the output of this run to
    # tests/snapshots/changed_two_projects.json.
    repo = two_project_repo(tmp_path)
    first, second = tmp_path / "a.json", tmp_path / "b.json"

    for target in (first, second):
        args = ["changed", "--base", "base", str(repo), "--json", str(target)]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.stderr
        assert f"JSON written to {target.as_posix()}" in result.stdout

    assert first.read_bytes() == second.read_bytes() == SNAPSHOT.read_bytes()


def test_json_root_holds_every_project_and_totals(tmp_path: Path) -> None:
    result = validate_changed(two_project_repo(tmp_path), "base")
    parsed = ChangedResult.model_validate_json(to_json(result))

    assert to_json(parsed) == to_json(result)
    assert [(p.path, p.status) for p in parsed.projects] == [
        ("reports/a/Sales.Report", ProjectStatus.CHANGED),
        ("reports/b/Sales.Report", ProjectStatus.CHANGED),
        ("reports/c/Sales.Report", ProjectStatus.ADDED),
    ]
    a, b, _ = parsed.projects
    assert a.result is not None and b.result is not None
    total = a.result.severity_counts.critical + b.result.severity_counts.critical
    assert parsed.severity_counts.critical == total


def test_cli_json_that_cannot_be_written_exits_with_1(repo: Path) -> None:
    put(repo, "sales_v2")
    target = repo / "missing" / "deeper" / "out.json"
    (repo / "missing").write_text("a file, not a folder", encoding="utf-8")

    result = runner.invoke(
        app, ["changed", "--base", "base", str(repo), "--json", str(target)]
    )

    assert result.exit_code == 1


MD_SNAPSHOT = SNAPSHOTS / "changed_two_projects.md"


def test_cli_markdown_for_two_projects_matches_snapshot(tmp_path: Path) -> None:
    # To update after an intended change, write the output of this run to
    # tests/snapshots/changed_two_projects.md.
    repo = two_project_repo(tmp_path)
    target = tmp_path / "changed.md"

    args = ["changed", "--base", "base", str(repo), "--markdown", str(target)]
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.stderr
    assert f"Markdown written to {target.as_posix()}" in result.stdout
    assert target.read_bytes() == MD_SNAPSHOT.read_bytes()
