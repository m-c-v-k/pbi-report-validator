"""Read report templates shipped inside the package."""

from importlib.resources import files

TEMPLATE_PACKAGE = "pbi_report_validator.reporting.templates"


class TemplateNotFoundError(Exception):
    """A template file is missing from the installed package."""


def read_template(name: str) -> str:
    """Return the source of a template in ``reporting/templates``.

    Raises:
        TemplateNotFoundError: The template is not part of the package.
    """
    resource = files(TEMPLATE_PACKAGE).joinpath(name)
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise TemplateNotFoundError(f"template {name} not found") from exc
