"""Entry point for the ``pbi-validate`` command line interface."""

import logging
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from pbi_report_validator.integrations.files import OutputWriteError, ProjectLoadError
from pbi_report_validator.reporting.terminal import format_summary
from pbi_report_validator.services.validate import (
    validate,
    write_json,
    write_markdown,
)

PACKAGE_NAME = "pbi-report-validator"
EXIT_ERROR = 1  # project could not be loaded or output not written

app = typer.Typer(
    name="pbi-validate",
    help="Compare two versions of a Power BI report and report what changed.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"pbi-validate {version(PACKAGE_NAME)}")
        raise typer.Exit


@app.callback()
def main(
    show_version: Annotated[
        bool,
        typer.Option(
            "--version",
            help="Show the version and exit.",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    """Compare two versions of a Power BI report and report what changed."""


@app.command()
def diff(
    old: Annotated[Path, typer.Argument(help="Old PBIP project or .Report folder.")],
    new: Annotated[Path, typer.Argument(help="New PBIP project or .Report folder.")],
    json_path: Annotated[
        Path | None,
        typer.Option("--json", help="Write the full result as JSON to this file."),
    ] = None,
    markdown_path: Annotated[
        Path | None,
        typer.Option(
            "--markdown",
            help="Write a Markdown summary (for PR comments) to this file.",
        ),
    ] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show progress logging.")
    ] = False,
) -> None:
    """Compare the structure of two report versions."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        result = validate(old, new)
        if json_path is not None:
            write_json(result, json_path)
        if markdown_path is not None:
            write_markdown(result, markdown_path)
    except (ProjectLoadError, OutputWriteError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    typer.echo(format_summary(result))
    for label, path in (("JSON", json_path), ("Markdown", markdown_path)):
        if path is not None:
            typer.echo(f"\n{label} written to {path.as_posix()}")
