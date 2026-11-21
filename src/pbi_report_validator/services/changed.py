"""Validate every report that changed between a git ref and the working tree.

A project is a ``<Name>.Report`` folder or a ``.pbit`` file. A changed
``<Name>.SemanticModel`` folder brings in every report that reads it. Each
project is compared with its version at the ref, exported to a temporary
folder; projects that exist on one side only are reported as added or removed.
"""

import logging
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from pbi_report_validator.domain.changed import (
    ChangedResult,
    ProjectRun,
    ProjectStatus,
)
from pbi_report_validator.domain.models import Severity
from pbi_report_validator.integrations.errors import ProjectLoadError
from pbi_report_validator.integrations.files import model_reference
from pbi_report_validator.integrations.git import (
    changed_files,
    files_at,
    repo_root,
    resolve_commit,
    snapshot,
    working_files,
)
from pbi_report_validator.services.validate import failure_reasons, validate

logger = logging.getLogger(__name__)

REPORT_SUFFIX = ".Report"
MODEL_SUFFIX = ".SemanticModel"
PBIT_SUFFIX = ".pbit"
MODEL_ONLY = (
    "semantic model changed, but no report in the repository reads it; "
    "a model on its own is compared from v0.10.0"
)


def validate_changed(path: Path, base: str) -> ChangedResult:
    """Compare every project under ``path`` that changed since ``base``.

    Args:
        path: A folder inside a git repository; only changes under it count.
        base: The git ref to compare with, e.g. ``origin/develop``.

    Returns:
        One run per project, ordered by path.

    Raises:
        GitError: The repository, the ref or a git command is unusable.
    """
    root = repo_root(path)
    commit = resolve_commit(root, base)
    scope = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())
    changed = _units(f for f in changed_files(root, commit) if _inside(f, scope))
    old_units = _units(files_at(root, commit))
    new_units = _units(working_files(root))
    # A model has no run of its own: the reports that read it show the change.
    models = {u for u in changed if u.endswith(MODEL_SUFFIX)}
    readers = _readers(root, models, new_units)
    projects = sorted(
        (changed - models) | {r for found in readers.values() for r in found}
    )
    # A removed model no report reads any more went with its reports.
    runs = [
        ProjectRun(path=m, status=ProjectStatus.SKIPPED, message=MODEL_ONLY)
        for m in sorted(models & new_units)
        if not readers[m]
    ]
    compared = [p for p in projects if p in old_units and p in new_units]
    runs += [_one_sided(p, p in new_units) for p in projects if p not in compared]
    with snapshot(root, commit, _folders(compared)) as old_root:
        runs += [_compare(old_root, root, p, base) for p in compared]
    return ChangedResult(base=base, projects=tuple(runs))


def run_failures(result: ChangedResult, fail_on: Severity | None) -> list[str]:
    """Why the run fails under ``--fail-on``, project by project."""
    reasons = []
    for run in result.projects:
        if run.status is ProjectStatus.REMOVED and fail_on is not None:
            reasons.append(f"{run.path}: project removed")
        if run.status is ProjectStatus.ADDED and fail_on is Severity.INFO:
            reasons.append(f"{run.path}: project added")
        if run.result is not None:
            failures = failure_reasons(run.result, fail_on, fail_on_data_error=False)
            # Reasons read "Failed: ..."; the CLI adds that prefix once.
            reasons += [f"{run.path}: {f.removeprefix('Failed: ')}" for f in failures]
    return reasons


def _units(files: Iterable[str]) -> set[str]:
    """The report folders, model folders and ``.pbit`` files ``files`` lie in."""
    return {unit for file in files if (unit := _unit(file)) is not None}


def _unit(file: str) -> str | None:
    parts = PurePosixPath(file).parts
    for index, part in enumerate(parts):
        if part.endswith((REPORT_SUFFIX, MODEL_SUFFIX)):
            return "/".join(parts[: index + 1])
    return file if file.lower().endswith(PBIT_SUFFIX) else None


def _inside(file: str, scope: PurePosixPath) -> bool:
    return str(scope) == "." or PurePosixPath(file).is_relative_to(scope)


def _readers(root: Path, models: set[str], reports: set[str]) -> dict[str, set[str]]:
    """The working-tree reports that read each changed or removed model.

    A report still pointing at a removed model is a reader, so its broken
    model reference is reported. A report whose model cannot be determined
    (a broken ``definition.pbir``) counts as a reader of every changed
    model, so its error is reported.
    """
    found: dict[str, set[str]] = {model: set() for model in models}
    targets = {(root / m).resolve(): m for m in models}
    for report in sorted(r for r in reports if r.endswith(REPORT_SUFFIX)):
        try:
            model_dir = model_reference(root / report)
        except ProjectLoadError as exc:
            logger.warning("Cannot tell which model %s reads: %s", report, exc)
            for readers in found.values():
                readers.add(report)
            continue
        model = targets.get(model_dir) if model_dir else None
        if model is not None:
            found[model].add(report)
    return found


def _folders(projects: list[str]) -> list[str]:
    """What to export for each project: the whole project folder of a report."""
    folders = {
        str(PurePosixPath(p).parent) if p.endswith(REPORT_SUFFIX) else p
        for p in projects
    }
    return sorted(folders)


def _one_sided(project: str, added: bool) -> ProjectRun:
    status = ProjectStatus.ADDED if added else ProjectStatus.REMOVED
    return ProjectRun(path=project, status=status)


def _compare(old_root: Path, new_root: Path, project: str, base: str) -> ProjectRun:
    """Compare one project; a project that cannot be loaded becomes an error run.

    Without data validation or the AI layer, ``validate`` raises only
    ``ProjectLoadError``: problems inside a project are findings. The sources
    name the ref and the project path, not the temporary folder.
    """
    try:
        result = validate(old_root / project, new_root / project)
    except ProjectLoadError as exc:
        return ProjectRun(path=project, status=ProjectStatus.ERROR, message=str(exc))
    sources = {"old_source": f"{base}:{project}", "new_source": project}
    return ProjectRun(
        path=project,
        status=ProjectStatus.CHANGED,
        result=result.model_copy(update=sources),
    )
