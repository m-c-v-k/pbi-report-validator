"""Entry point for the ``pbi-validate`` command line interface."""

from importlib.metadata import version
from typing import Annotated

import typer

PACKAGE_NAME = "pbi-report-validator"

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
