"""Entry point for the ``pbi-validate`` command line interface."""

import logging
import os
from importlib.metadata import version
from pathlib import Path
from typing import Annotated

import typer

from pbi_report_validator.integrations.config import MissingCredentialsError
from pbi_report_validator.integrations.files import OutputWriteError, ProjectLoadError
from pbi_report_validator.integrations.powerbi import PowerBIError
from pbi_report_validator.integrations.templates import TemplateNotFoundError
from pbi_report_validator.reporting.terminal import format_summary
from pbi_report_validator.services.data import (
    DataRun,
    InvalidDataOptionsError,
    create_runner,
    data_settings,
)
from pbi_report_validator.services.validate import (
    validate,
    write_html,
    write_json,
    write_markdown,
)

PACKAGE_NAME = "pbi-report-validator"
EXIT_ERROR = 1  # project not loadable, output not writable or data validation failed
EXIT_USAGE = 2  # invalid combination of options

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
    html_path: Annotated[
        Path | None,
        typer.Option("--html", help="Write a self-contained HTML report to this file."),
    ] = None,
    data: Annotated[
        bool,
        typer.Option(
            "--data",
            help="Also compare the numbers: run each visual as a DAX query against "
            "the old and new published datasets (needs PBI_* credentials).",
        ),
    ] = False,
    old_dataset: Annotated[
        str | None, typer.Option("--old-dataset", help="Dataset id of the old version.")
    ] = None,
    new_dataset: Annotated[
        str | None, typer.Option("--new-dataset", help="Dataset id of the new version.")
    ] = None,
    abs_tol: Annotated[
        float,
        typer.Option("--abs-tol", min=0, help="Allowed absolute difference."),
    ] = 0.0,
    rel_tol: Annotated[
        float,
        typer.Option("--rel-tol", min=0, help="Allowed relative difference."),
    ] = 1e-9,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show progress logging.")
    ] = False,
) -> None:
    """Compare two report versions: structure, and with --data also the numbers."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = (
            data_settings(old_dataset, new_dataset, abs_tol, rel_tol) if data else None
        )
    except InvalidDataOptionsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from exc
    try:
        run = DataRun(settings, create_runner(os.environ)) if settings else None
        result = validate(old, new, run)
        if json_path is not None:
            write_json(result, json_path)
        if markdown_path is not None:
            write_markdown(result, markdown_path)
        if html_path is not None:
            write_html(result, html_path, version(PACKAGE_NAME))
    except (
        ProjectLoadError,
        OutputWriteError,
        TemplateNotFoundError,
        MissingCredentialsError,
        PowerBIError,
    ) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(EXIT_ERROR) from exc
    typer.echo(format_summary(result))
    outputs = (("JSON", json_path), ("Markdown", markdown_path), ("HTML", html_path))
    for label, path in outputs:
        if path is not None:
            typer.echo(f"\n{label} written to {path.as_posix()}")
