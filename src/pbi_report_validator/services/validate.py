"""Orchestrate a structural validation run: load, parse, match, diff."""

import logging
from pathlib import Path

from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.diff.structural import (
    diff_pages_and_visuals,
    without_unparseable,
)
from pbi_report_validator.diff.view import build_page_views
from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DiffResult,
    Finding,
    ParseIssue,
    Report,
    SemanticModel,
)
from pbi_report_validator.domain.raw import RawProject
from pbi_report_validator.integrations.files import load_project, write_text
from pbi_report_validator.integrations.templates import read_template
from pbi_report_validator.matching.matcher import match_reports
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from pbi_report_validator.reporting.html import REPORT_TEMPLATE, to_html
from pbi_report_validator.reporting.json_out import to_json
from pbi_report_validator.reporting.markdown import to_markdown
from pbi_report_validator.services.data import DataRun, validate_data

logger = logging.getLogger(__name__)


def validate(
    old_path: Path,
    new_path: Path,
    data: DataRun | None = None,
) -> DiffResult:
    """Compare two PBIP projects structurally and, optionally, their data.

    Args:
        old_path: The old project folder (or its ``.Report`` folder).
        new_path: The new project folder (or its ``.Report`` folder).
        data: Datasets, tolerance and query runner for data validation;
            ``None`` skips it.

    Returns:
        All findings, including parse issues of either version.

    Raises:
        ProjectLoadError: A project could not be loaded at all.
        PowerBIError: Data validation could not sign in or find a dataset.
    """
    old_report, old_model = _parse(load_project(old_path))
    new_report, new_model = _parse(load_project(new_path))
    match = match_reports(old_report.pages, new_report.pages)
    measures = diff_measures(old_model, new_model)
    structural = without_unparseable(
        diff_pages_and_visuals(match), old_report.issues, new_report.issues
    )
    findings = [
        *structural,
        *measures.findings,
        *diff_content(old_report, new_report, match, measures.renames),
        *_issue_findings("old", old_report, old_model),
        *_issue_findings("new", new_report, new_model),
    ]
    comparisons = []
    if data is not None:
        comparisons = validate_data(
            old_report,
            new_report,
            match,
            measures.renames,
            data.runner,
            data.settings,
        )
        findings += [f for c in comparisons for f in c.findings]
    logger.info("Found %d findings", len(findings))
    return DiffResult(
        old_source=old_path.as_posix(),
        new_source=new_path.as_posix(),
        findings=tuple(findings),
        pages=build_page_views(match, findings),
        data=tuple(sorted((c.summary for c in comparisons), key=lambda s: s.path)),
    )


def write_json(result: DiffResult, path: Path) -> None:
    """Write the result as JSON to ``path``.

    Raises:
        OutputWriteError: The file could not be written.
    """
    write_text(path, to_json(result))


def write_html(result: DiffResult, path: Path, tool_version: str) -> None:
    """Write the result as a self-contained HTML report to ``path``.

    Raises:
        OutputWriteError: The file could not be written.
        TemplateNotFoundError: The report template is missing.
    """
    write_text(path, to_html(result, read_template(REPORT_TEMPLATE), tool_version))


def write_markdown(result: DiffResult, path: Path) -> None:
    """Write the result as a Markdown summary to ``path``.

    Raises:
        OutputWriteError: The file could not be written.
    """
    write_text(path, to_markdown(result))


def _parse(project: RawProject) -> tuple[Report, SemanticModel | None]:
    report = parse_report(project.report)
    model = (
        parse_semantic_model(project.semantic_model) if project.semantic_model else None
    )
    return report, model


def _issue_findings(
    side: str, report: Report, model: SemanticModel | None
) -> list[Finding]:
    issues: list[ParseIssue] = [*report.issues, *(model.issues if model else ())]
    return [
        Finding(
            category=Category.PARSE_ISSUE,
            change=ChangeKind.ERROR,
            path=f"{side}/{issue.path}",
            message=f"Could not fully parse the {side} version: {issue.message}",
            visual=issue.visual,
        )
        for issue in issues
    ]
