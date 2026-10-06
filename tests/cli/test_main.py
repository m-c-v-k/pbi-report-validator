from importlib.metadata import version

from typer.testing import CliRunner

from pbi_report_validator.cli.main import PACKAGE_NAME, app

runner = CliRunner()


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"pbi-validate {version(PACKAGE_NAME)}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output
