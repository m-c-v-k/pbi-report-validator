"""Detect the input format and read a PBIP project from disk.

This is the only module in the validation flow that touches the filesystem.
Paths in the returned models are POSIX paths relative to the project folder,
so the output does not depend on where the project lives.
"""

import json
import logging
import os
from collections.abc import Callable, Iterable
from pathlib import Path

from pbi_report_validator.domain.raw import (
    InputFormat,
    RawJsonFile,
    RawLegacyReport,
    RawPage,
    RawProject,
    RawReport,
    RawSemanticModel,
    RawTextFile,
)

logger = logging.getLogger(__name__)

REPORT_SUFFIX = ".Report"
MODEL_SUFFIX = ".SemanticModel"
PBIP_SUFFIX = ".pbip"
FILE_FORMATS = {".pbit": InputFormat.PBIT, ".pbix": InputFormat.PBIX}
PROJECT_FORMATS = frozenset({InputFormat.PBIP_PBIR, InputFormat.PBIP_LEGACY})
SAVE_AS_PBIP = "save the report as a Power BI Project (.pbip)"
UNSUPPORTED_REASONS = {
    InputFormat.PBIT: f".pbit files are not supported yet (planned for v0.7.0); "
    f"{SAVE_AS_PBIP}",
    InputFormat.PBIX: f".pbix files are not supported yet (planned for v0.9.0); "
    f"{SAVE_AS_PBIP}",
    InputFormat.SEMANTIC_MODEL: "a semantic model on its own is not supported yet "
    "(planned for v0.10.0); pass the PBIP project folder or its .Report folder",
    InputFormat.UNKNOWN: "not a supported input; expected a PBIP project folder, "
    "a .Report folder or a .pbip file",
}


class ProjectLoadError(Exception):
    """Base class for errors that prevent loading a project."""


class ProjectNotFoundError(ProjectLoadError):
    """The path does not contain exactly one ``<Name>.Report`` folder."""


class MissingDefinitionError(ProjectLoadError):
    """A ``.Report`` folder has neither a PBIR nor a legacy ``report.json``."""


class UnsupportedInputError(ProjectLoadError):
    """The path is an input format that ``diff`` cannot read (yet)."""

    def __init__(self, path: Path, input_format: InputFormat) -> None:
        """Create the error for ``path``, detected as ``input_format``."""
        super().__init__(f"{path}: {UNSUPPORTED_REASONS[input_format]}")
        self.path = path
        self.input_format = input_format


class ModelOutsideProjectError(ProjectLoadError):
    """``definition.pbir`` points to a semantic model outside the project."""


class InvalidJsonError(ProjectLoadError):
    """A file the whole report depends on is unreadable or not valid JSON."""

    def __init__(self, path: str, reason: str) -> None:
        """Create the error for ``path`` with the parser's ``reason``."""
        super().__init__(f"{path}: invalid JSON ({reason})")
        self.path = path


class UnreadableFolderError(ProjectLoadError):
    """A folder in the project could not be listed."""

    def __init__(self, path: str, reason: str) -> None:
        """Create the error for folder ``path`` with the underlying ``reason``."""
        super().__init__(f"{path}: could not list folder ({reason})")
        self.path = path


class OutputWriteError(Exception):
    """An output file (e.g. the JSON report) could not be written."""


def load_project(path: Path) -> RawProject:
    """Load a PBIP project.

    Args:
        path: A folder containing one ``<Name>.Report`` folder (a PBIP
            project folder), the ``<Name>.Report`` folder itself or the
            project's ``.pbip`` file.

    Returns:
        The raw report contents and, if the report references its semantic
        model by path (or is ``byConnection`` with a ``<Name>.SemanticModel``
        folder next to it), the model's TMDL files (an unreadable one is
        kept with its error); otherwise why there is no model to read.

    Raises:
        UnsupportedInputError: The path is not a PBIP project (see
            ``detect_input``).
        ProjectNotFoundError: No single ``.Report`` folder was found.
        MissingDefinitionError: The report has neither a PBIR definition
            nor a legacy ``report.json``.
        InvalidJsonError: ``report.json``, ``pages.json`` or ``definition.pbir``
            is unreadable or not valid JSON.
        UnreadableFolderError: A project folder could not be listed.
        ModelOutsideProjectError: ``definition.pbir`` points to a semantic
            model outside the project folder.
    """
    input_format = detect_input(path)
    if input_format not in PROJECT_FORMATS:
        raise UnsupportedInputError(path, input_format)
    report_dir = _find_report_dir(path)
    root = report_dir.parent
    name = report_dir.name.removesuffix(REPORT_SUFFIX)
    model_dir, missing = _find_model_dir(report_dir, root)
    model = _load_semantic_model(model_dir, root) if model_dir else None
    if model_dir and model is None:
        missing = _empty_model_reason(model_dir, root)
    return RawProject(
        name=name,
        report=_load_report(report_dir, root),
        semantic_model=model,
        model_missing=missing,
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


def detect_input(path: Path) -> InputFormat:
    """What kind of input ``path`` is, from its name and the files it holds.

    A file is detected by its extension; a ``.pbip`` file and a folder by
    the report they lead to. A ``.SemanticModel`` folder, or a folder with
    a semantic model and no report, is a semantic model on its own.

    Raises:
        ProjectNotFoundError: The path does not exist, or a folder holds no
            report and no model, or several ``.Report`` folders.
        MissingDefinitionError: The report has neither a PBIR definition
            nor a legacy ``report.json``.
        InvalidJsonError: A ``.pbip`` file is unreadable or not valid JSON.
        UnreadableFolderError: A folder could not be listed.
    """
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == PBIP_SUFFIX:
            return _report_format(_report_dir_from_pbip(path))
        return FILE_FORMATS.get(suffix, InputFormat.UNKNOWN)
    if path.is_dir() and _is_model_only(path):
        return InputFormat.SEMANTIC_MODEL
    return _report_format(_find_report_dir(path))


def _is_model_only(folder: Path) -> bool:
    if folder.name.endswith(MODEL_SUFFIX):
        return True
    if folder.name.endswith(REPORT_SUFFIX):
        return False
    return not _subdirs(folder, REPORT_SUFFIX) and bool(_subdirs(folder, MODEL_SUFFIX))


def _report_format(report_dir: Path) -> InputFormat:
    if (report_dir / "definition" / "report.json").is_file():
        return InputFormat.PBIP_PBIR
    if (report_dir / "report.json").is_file():
        return InputFormat.PBIP_LEGACY
    raise MissingDefinitionError(
        f"{report_dir} has neither definition/report.json (PBIR)"
        " nor report.json (legacy format)"
    )


def _report_dir_from_pbip(file: Path) -> Path:
    """The report folder the first report artifact of a ``.pbip`` points to."""
    project = file.parent
    artifacts = _read_required_json(file, project).content.get("artifacts")
    for artifact in artifacts if isinstance(artifacts, list) else []:
        report = artifact.get("report") if isinstance(artifact, dict) else None
        relative = report.get("path") if isinstance(report, dict) else None
        if isinstance(relative, str):
            report_dir = (project / relative).resolve()
            if not report_dir.is_relative_to(project.resolve()):
                raise ProjectNotFoundError(f"{file} points outside its folder")
            if not report_dir.is_dir():
                raise ProjectNotFoundError(f"{file} points to missing {relative}")
            return report_dir
    raise ProjectNotFoundError(f"{file} lists no report")


def _find_report_dir(path: Path) -> Path:
    if path.is_file():
        return _report_dir_from_pbip(path)
    if not path.is_dir():
        raise ProjectNotFoundError(f"{path} is not a folder")
    if path.name.endswith(REPORT_SUFFIX):
        return path
    candidates = _subdirs(path, REPORT_SUFFIX)
    if len(candidates) != 1:
        found = ", ".join(p.name for p in candidates) or "none"
        raise ProjectNotFoundError(
            f"expected exactly one *{REPORT_SUFFIX} folder in {path}, found {found}"
        )
    return candidates[0]


def _find_model_dir(report_dir: Path, root: Path) -> tuple[Path | None, str | None]:
    """The semantic model folder, or ``None`` and why there is none.

    A ``byConnection`` report (one connected to a published model) still
    uses the sibling ``<Name>.SemanticModel`` folder when there is one, so
    a published report saved next to its model compares its measures.
    """
    pbir = report_dir / "definition.pbir"
    sibling = report_dir.with_name(
        report_dir.name.removesuffix(REPORT_SUFFIX) + MODEL_SUFFIX
    )
    if pbir.is_file():
        reference = _read_required_json(pbir, report_dir.parent)
        dataset = reference.content.get("datasetReference")
        by_path = dataset.get("byPath") if isinstance(dataset, dict) else None
        if isinstance(by_path, dict) and isinstance(by_path.get("path"), str):
            model_path: str = by_path["path"]
            candidate = (report_dir / model_path).resolve()
            _require_inside(candidate, report_dir.parent.resolve(), pbir.name)
            if candidate.is_dir():
                return candidate, None
            logger.warning("%s points to missing folder %s", pbir.name, candidate)
            return None, f"{pbir.name} points to a folder that does not exist"
        by_connection = isinstance(dataset, dict) and "byConnection" in dataset
        if by_connection and sibling.is_dir():
            logger.info("%s uses byConnection; reading %s", pbir.name, sibling.name)
            return sibling, None
        logger.info("%s has no byPath dataset reference", pbir.name)
        return None, "the report uses a published semantic model (byConnection)"
    if sibling.is_dir():
        return sibling, None
    return None, f"no {sibling.name} folder next to {_relative(report_dir, root)}"


def _empty_model_reason(model_dir: Path, root: Path) -> str:
    return f"{_relative(model_dir, root)} has no .tmdl files and no model.bim"


def _require_inside(path: Path, root: Path, source: str) -> None:
    if not path.is_relative_to(root):
        raise ModelOutsideProjectError(
            f"{source} points to {path}, which is outside the project folder {root}"
        )


def _load_report(report_dir: Path, root: Path) -> RawReport | RawLegacyReport:
    """The PBIR ``definition`` folder, else the legacy-format ``report.json``."""
    if _report_format(report_dir) is InputFormat.PBIP_PBIR:
        return _load_pbir_report(report_dir, root)
    return RawLegacyReport(
        path=_relative(report_dir, root),
        layout=_read_required_json(report_dir / "report.json", root),
    )


def _load_pbir_report(report_dir: Path, root: Path) -> RawReport:
    definition = report_dir / "definition"
    report_json = definition / "report.json"
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


def _load_semantic_model(model_dir: Path, root: Path) -> RawSemanticModel | None:
    """The model's TMDL files, else its ``model.bim``; ``None`` if neither."""
    definition = model_dir / "definition"
    files = (
        sorted(
            _list(definition, lambda: definition.rglob("*.tmdl")),
            key=lambda p: p.relative_to(definition),
        )
        if definition.is_dir()
        else []
    )
    path = _relative(model_dir, root)
    if files:
        return RawSemanticModel(
            path=path, files=tuple(_read_text(f, root) for f in files)
        )
    bim = model_dir / "model.bim"
    if bim.is_file():
        return RawSemanticModel(path=path, bim=_read_json(bim, root))
    return None


def _read_text(path: Path, root: Path) -> RawTextFile:
    relative = _relative(path, root)
    try:
        return RawTextFile(path=relative, text=path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Could not read %s: %s", relative, exc)
        return RawTextFile(path=relative, error=str(exc))


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


def _subdirs(folder: Path, suffix: str) -> list[Path]:
    """The folders in ``folder`` whose name ends with ``suffix``, sorted."""
    entries = _list(folder, lambda: folder.glob(f"*{suffix}"))
    return sorted(p for p in entries if p.is_dir())


def _sorted_subdirs(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in _list(path, path.iterdir) if p.is_dir())


def _list(folder: Path, entries: Callable[[], Iterable[Path]]) -> list[Path]:
    """Collect ``entries()``, turning listing failures into a typed error."""
    try:
        return list(entries())
    except OSError as exc:
        raise UnreadableFolderError(str(folder), str(exc)) from exc


def _relative(path: Path, root: Path) -> str:
    """Path relative to ``root``, with ``..`` segments if it lies outside."""
    try:
        return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()
    except ValueError:  # different drive on Windows, no relative path exists
        return path.name
