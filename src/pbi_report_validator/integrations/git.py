"""Read a git repository through the ``git`` command line.

Only reads: nothing is fetched, checked out or written to the repository. The
base version of a project is copied blob by blob (``ls-tree`` and
``cat-file``) into a temporary folder that is removed afterwards, so
``.gitattributes`` export rules cannot hide or rewrite files, and size limits
apply before anything is read. Paths are POSIX paths relative to the
repository root, as git prints them. Pathspecs are literal, git never prompts,
and every command has a timeout.
"""

import logging
import os
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import NamedTuple

from pbi_report_validator.integrations.archives import ArchiveLimits

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 120.0
SYMLINK_MODE = "120000"
NOT_A_REPOSITORY = "not a git repository"
GIT_ENV = {"GIT_LITERAL_PATHSPECS": "1", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
FETCH_HINT = (
    "fetch it first (git fetch origin {ref}), or in GitHub Actions check out "
    "the full history (actions/checkout with fetch-depth: 0)"
)


class GitError(Exception):
    """A git command could not give what was asked."""


class GitUnavailableError(GitError):
    """The ``git`` command is not installed or not on ``PATH``."""


class NotARepositoryError(GitError):
    """The path is not inside a git repository."""


class UnknownRefError(GitError):
    """The ref does not name a commit in the local repository."""


class GitCommandError(GitError):
    """A git command failed or printed something unreadable."""


class GitTimeoutError(GitError):
    """A git command did not finish in time."""


class SnapshotTooLargeError(GitError):
    """The folders to copy hold more files or bytes than the limits allow."""


class _Blob(NamedTuple):
    object_id: str
    path: str


def repo_root(path: Path) -> Path:
    """The root folder of the repository ``path`` is in.

    Raises:
        NotARepositoryError: ``path`` is not inside a git repository.
        GitCommandError: git failed for another reason, e.g. dubious ownership.
        GitUnavailableError: ``git`` is not installed.
    """
    folder = path if path.is_dir() else path.parent
    if not folder.is_dir():
        raise NotARepositoryError(f"{path} does not exist")
    try:
        return Path(_git(folder, "rev-parse", "--show-toplevel").decode().strip())
    except GitCommandError as exc:
        if NOT_A_REPOSITORY in str(exc).lower():
            raise NotARepositoryError(f"{path} is not inside a git repository") from exc
        raise


def resolve_commit(root: Path, ref: str) -> str:
    """The commit id ``ref`` names, without fetching anything.

    Raises:
        UnknownRefError: The ref is not available locally (for example in a
            shallow clone), or looks like an option.
    """
    error = UnknownRefError(
        f"git ref {ref!r} is not available locally; " + FETCH_HINT.format(ref=ref)
    )
    if not ref or ref.startswith("-"):
        raise error
    try:
        output = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except GitCommandError as exc:
        raise error from exc
    return output.decode().strip()


def changed_files(path: Path, commit: str) -> list[str]:
    """Files that differ between ``commit`` and the working tree, untracked included.

    ``path`` may be any folder in the repository; the whole repository counts.
    """
    root = repo_root(path)
    tracked = _git(root, "diff", "--name-only", "--no-renames", "-z", commit, "--")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(set(_paths(tracked)) | set(_paths(untracked)))


def files_at(path: Path, commit: str) -> list[str]:
    """Every file in ``commit``; ``path`` may be any folder in the repository."""
    return _paths(
        _git(path, "ls-tree", "-r", "--full-tree", "--name-only", "-z", commit)
    )


def working_files(path: Path) -> list[str]:
    """Every file in the working tree that git tracks or would track."""
    root = repo_root(path)
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return [p for p in _paths(listed) if (root / p).is_file()]


@contextmanager
def snapshot(
    root: Path,
    commit: str,
    folders: Sequence[str],
    limits: ArchiveLimits | None = None,
) -> Iterator[Path]:
    """A temporary folder holding ``folders`` (and files) as they were in ``commit``.

    Symbolic links and submodules are left out; a folder missing from
    ``commit`` gives nothing.

    Raises:
        SnapshotTooLargeError: The folders exceed ``limits``.
        GitCommandError: git failed or printed something unreadable.
    """
    with tempfile.TemporaryDirectory(prefix="pbi-validate-") as target:
        if folders:
            blobs = _list_blobs(root, commit, folders, limits or ArchiveLimits())
            _write_blobs(root, Path(target), blobs)
        yield Path(target)


def _list_blobs(
    root: Path, commit: str, folders: Sequence[str], limits: ArchiveLimits
) -> list[_Blob]:
    """The files under ``folders`` in ``commit``, checked against ``limits``."""
    listing = _git(
        root, "ls-tree", "-r", "-l", "-z", "--full-tree", commit, "--", *folders
    )
    blobs: list[_Blob] = []
    total = 0
    for entry in _paths(listing):
        meta, _, path = entry.partition("\t")
        mode, kind, object_id, size = meta.split()
        if kind != "blob" or mode == SYMLINK_MODE:
            logger.info("Leaving out %s %s from the snapshot", kind, path)
            continue
        total += int(size)
        if int(size) > limits.entry_bytes or total > limits.total_bytes:
            raise SnapshotTooLargeError(f"{commit}: files under {path} are too large")
        blobs.append(_Blob(object_id, path))
    if len(blobs) > limits.entries:
        raise SnapshotTooLargeError(f"{commit}: more than {limits.entries} files")
    return blobs


def _write_blobs(root: Path, target: Path, blobs: list[_Blob]) -> None:
    """Write each blob's contents to its path under ``target``."""
    ids = "".join(f"{blob.object_id}\n" for blob in blobs).encode()
    output = _git(root, "cat-file", "--batch", stdin=ids)
    offset = 0
    for blob in blobs:
        header_end = output.index(b"\n", offset)
        size = int(output[offset:header_end].split()[2])
        start = header_end + 1
        _write_file(target, blob.path, output[start : start + size])
        offset = start + size + 1


def _write_file(target: Path, path: str, content: bytes) -> None:
    parts = PurePosixPath(path).parts
    if PurePosixPath(path).is_absolute() or ".." in parts:
        raise GitCommandError(f"git printed a path that escapes the snapshot: {path}")
    destination = target.joinpath(*parts)
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    except OSError as exc:
        raise GitCommandError(f"could not write {path}: {exc}") from exc


def _paths(output: bytes) -> list[str]:
    try:
        return [p for p in output.decode("utf-8").split("\0") if p]
    except UnicodeDecodeError as exc:
        raise GitCommandError(f"git printed a path that is not UTF-8: {exc}") from exc


def _git(cwd: Path, *args: str, stdin: bytes | None = None) -> bytes:
    """Run ``git`` in ``cwd`` and return what it printed."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            input=stdin,
            capture_output=True,
            check=False,
            timeout=TIMEOUT_SECONDS,
            env={**os.environ, **GIT_ENV},
        )
    except FileNotFoundError as exc:
        raise GitUnavailableError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitTimeoutError(
            f"git {args[0]} took over {TIMEOUT_SECONDS:.0f}s"
        ) from exc
    except OSError as exc:
        raise GitCommandError(f"could not run git in {cwd}: {exc}") from exc
    if done.returncode != 0:
        message = done.stderr.decode(errors="replace").strip()
        raise GitCommandError(f"git {args[0]} failed: {message}")
    return done.stdout
