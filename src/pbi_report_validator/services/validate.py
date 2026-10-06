"""Orchestrate a structural validation run: load, parse, match, diff."""

import logging
from pathlib import Path

from pbi_report_validator.diff.content import diff_content
from pbi_report_validator.diff.measures import diff_measures
from pbi_report_validator.diff.structural import diff_pages_and_visuals
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
from pbi_report_validator.matching.matcher import match_reports
from pbi_report_validator.parsers.pbir import parse_report
from pbi_report_validator.parsers.tmdl import parse_semantic_model
from pbi_report_validator.reporting.json_out import to_json

logger = logging.getLogger(__name__)


def validate(old_path: Path, new_path: Path) -> DiffResult:
    """Compare two PBIP projects structurally.

    Args:
        old_path: The old project folder (or its ``.Report`` folder).
        new_path: The new project folder (or its ``.Report`` folder).

    Returns:
        All findings, including parse issues of either version.

    Raises:
        ProjectLoadError: A project could not be loaded at all.
    """
    old_report, old_model = _parse(load_project(old_path))
    new_report, new_model = _parse(load_project(new_path))
    match = match_reports(old_report.pages, new_report.pages)
    measures = diff_measures(old_model, new_model)
    findings = [
        *diff_pages_and_visuals(match),
        *measures.findings,
        *diff_content(old_report, new_report, match, measures.renames),
        *_issue_findings("old", old_report, old_model),
        *_issue_findings("new", new_report, new_model),
    ]
    logger.info("Found %d findings", len(findings))
    return DiffResult(
        old_source=old_path.as_posix(),
        new_source=new_path.as_posix(),
        findings=tuple(findings),
    )


def write_json(result: DiffResult, path: Path) -> None:
    """Write the result as JSON to ``path``.

    Raises:
        OutputWriteError: The file could not be written.
    """
    write_text(path, to_json(result))


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
        )
        for issue in issues
    ]
