"""Read a PBIP project (PBIR report + TMDL semantic model) from disk.

This is the only module in the validation flow that touches the filesystem.
Paths in the returned models are POSIX paths relative to the project folder,
so the output does not depend on where the project lives.
"""

import json
import logging
import os
from pathlib import Path

from pbi_report_validator.domain.raw import (
    RawJsonFile,
    RawPage,
    RawProject,
    RawReport,
    RawSemanticModel,
    RawTextFile,
)

logger = logging.getLogger(__name__)

REPORT_SUFFIX = ".Report"
MODEL_SUFFIX = ".SemanticModel"


class ProjectLoadError(Exception):
    """Base class for errors that prevent loading a project."""


class ProjectNotFoundError(ProjectLoadError):
    """The path does not contain exactly one ``<Name>.Report`` folder."""


class MissingDefinitionError(ProjectLoadError):
    """A ``.Report`` folder has no PBIR ``definition/report.json``."""


class InvalidJsonError(ProjectLoadError):
    """A file the whole report depends on is unreadable or not valid JSON."""

    def __init__(self, path: str, reason: str) -> None:
        """Create the error for ``path`` with the parser's ``reason``."""
        super().__init__(f"{path}: invalid JSON ({reason})")
        self.path = path


class UnreadableFileError(ProjectLoadError):
    """A semantic model file could not be read as UTF-8 text."""

    def __init__(self, path: str, reason: str) -> None:
        """Create the error for ``path`` with the underlying ``reason``."""
        super().__init__(f"{path}: could not read file ({reason})")
        self.path = path


class OutputWriteError(Exception):
    """An output file (e.g. the JSON report) could not be written."""


def load_project(path: Path) -> RawProject:
    """Load a PBIP project.

    Args:
        path: Either a folder containing one ``<Name>.Report`` folder (a PBIP
            project folder) or the ``<Name>.Report`` folder itself.

    Returns:
        The raw report contents and, if the report references its semantic
        model by path, the model's TMDL files.

    Raises:
        ProjectNotFoundError: No single ``.Report`` folder was found.
        MissingDefinitionError: The report is not in PBIR format.
        InvalidJsonError: ``report.json``, ``pages.json`` or ``definition.pbir``
            is unreadable or not valid JSON.
        UnreadableFileError: A ``.tmdl`` file could not be read.
    """
    report_dir = _find_report_dir(path)
    root = report_dir.parent
    name = report_dir.name.removesuffix(REPORT_SUFFIX)
    model_dir = _find_model_dir(report_dir)
    return RawProject(
        name=name,
        report=_load_report(report_dir, root),
        semantic_model=_load_semantic_model(model_dir, root) if model_dir else None,
    )


def write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with LF line endings, creating parent folders.

    Raises:
        OutputWriteError: The file could not be written.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise OutputWriteError(f"could not write {path}: {exc}") from exc


def _find_report_dir(path: Path) -> Path:
    if not path.is_dir():
        raise ProjectNotFoundError(f"{path} is not a folder")
    if path.name.endswith(REPORT_SUFFIX):
        return path
    candidates = sorted(p for p in path.glob(f"*{REPORT_SUFFIX}") if p.is_dir())
    if len(candidates) != 1:
        found = ", ".join(p.name for p in candidates) or "none"
        raise ProjectNotFoundError(
            f"expected exactly one *{REPORT_SUFFIX} folder in {path}, found {found}"
        )
    return candidates[0]


def _find_model_dir(report_dir: Path) -> Path | None:
    pbir = report_dir / "definition.pbir"
    if pbir.is_file():
        reference = _read_required_json(pbir, report_dir.parent)
        by_path = reference.content.get("datasetReference", {}).get("byPath", {})
        if isinstance(by_path, dict) and isinstance(by_path.get("path"), str):
            model_path: str = by_path["path"]
            candidate = (report_dir / model_path).resolve()
            if candidate.is_dir():
                return candidate
            logger.warning("%s points to missing folder %s", pbir.name, candidate)
            return None
        logger.info("%s has no byPath dataset reference", pbir.name)
        return None
    sibling = report_dir.with_name(
        report_dir.name.removesuffix(REPORT_SUFFIX) + MODEL_SUFFIX
    )
    return sibling if sibling.is_dir() else None


def _load_report(report_dir: Path, root: Path) -> RawReport:
    definition = report_dir / "definition"
    report_json = definition / "report.json"
    if not report_json.is_file():
        raise MissingDefinitionError(
            f"{_relative(report_json, root)} not found; save the report in PBIR format"
        )
    pages_dir = definition / "pages"
    pages_json = pages_dir / "pages.json"
    return RawReport(
        path=_relative(report_dir, root),
        report=_read_required_json(report_json, root),
        pages_meta=_read_required_json(pages_json, root)
        if pages_json.is_file()
        else None,
        pages=tuple(
            _load_page(page_dir, root)
            for page_dir in _sorted_subdirs(pages_dir)
            if (page_dir / "page.json").is_file()
        ),
    )


def _load_page(page_dir: Path, root: Path) -> RawPage:
    visuals = tuple(
        _read_json(visual_dir / "visual.json", root)
        for visual_dir in _sorted_subdirs(page_dir / "visuals")
        if (visual_dir / "visual.json").is_file()
    )
    return RawPage(
        name=page_dir.name,
        page=_read_json(page_dir / "page.json", root),
        visuals=visuals,
    )


def _load_semantic_model(model_dir: Path, root: Path) -> RawSemanticModel:
    definition = model_dir / "definition"
    files = sorted(definition.rglob("*.tmdl"), key=lambda p: p.relative_to(definition))
    return RawSemanticModel(
        path=_relative(model_dir, root),
        files=tuple(_read_text(f, root) for f in files),
    )


def _read_text(path: Path, root: Path) -> RawTextFile:
    relative = _relative(path, root)
    try:
        return RawTextFile(path=relative, text=path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        raise UnreadableFileError(relative, str(exc)) from exc


def _read_required_json(path: Path, root: Path) -> RawJsonFile:
    raw = _read_json(path, root)
    if raw.error is not None:
        raise InvalidJsonError(raw.path, raw.error)
    return raw


def _read_json(path: Path, root: Path) -> RawJsonFile:
    relative = _relative(path, root)
    try:
        content = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Could not read %s: %s", relative, exc)
        return RawJsonFile(path=relative, error=str(exc))
    if not isinstance(content, dict):
        return RawJsonFile(path=relative, error="top-level value is not an object")
    return RawJsonFile(path=relative, content=content)


def _sorted_subdirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.iterdir() if p.is_dir())


def _relative(path: Path, root: Path) -> str:
    """Path relative to ``root``, with ``..`` segments if it lies outside."""
    try:
        return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()
    except ValueError:  # different drive on Windows, no relative path exists
        return path.name
