import json
import os
import shutil
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

from typer.testing import CliRunner

from pbi_report_validator.cli.main import PACKAGE_NAME, app
from tests.factories import FIXTURES

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"pbi-validate {version(PACKAGE_NAME)}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output


def test_summary_survives_a_non_utf8_stdout(tmp_path: Path) -> None:
    old = shutil.copytree(FIXTURES / "sales_v1", tmp_path / "old")
    new = shutil.copytree(FIXTURES / "sales_v1", tmp_path / "new")
    page = new / "Sales.Report/definition/pages/details/page.json"
    content = json.loads(page.read_text(encoding="utf-8-sig"))
    content["displayName"] = "Détails 📊"
    page.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    code = "from pbi_report_validator.cli.main import app; app()"
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"}

    result = subprocess.run(
        [sys.executable, "-c", code, "diff", str(old), str(new)],
        capture_output=True,
        env=env,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("cp1252")
    assert "Détails ?" in result.stdout.decode("cp1252")
