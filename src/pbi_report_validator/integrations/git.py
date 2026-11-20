"""Read a git repository through the ``git`` command line.

Only reads: nothing is fetched, checked out or written to the repository. The
base version of a project is exported with ``git archive`` into a temporary
folder that is removed afterwards. Paths are POSIX paths relative to the
repository root, as git prints them.
"""

import io
import subprocess
import tarfile
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

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


def repo_root(path: Path) -> Path:
    """The root folder of the repository ``path`` is in.

    Raises:
        NotARepositoryError: ``path`` is not inside a git repository.
        GitUnavailableError: ``git`` is not installed.
    """
    folder = path if path.is_dir() else path.parent
    try:
        return Path(_git(folder, "rev-parse", "--show-toplevel").decode().strip())
    except GitCommandError as exc:
        raise NotARepositoryError(f"{path} is not inside a git repository") from exc


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


def changed_files(root: Path, commit: str) -> list[str]:
    """Files that differ between ``commit`` and the working tree, untracked included."""
    tracked = _git(root, "diff", "--name-only", "--no-renames", "-z", commit, "--")
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(set(_paths(tracked)) | set(_paths(untracked)))


def files_at(root: Path, commit: str) -> list[str]:
    """Every file in ``commit``."""
    return _paths(_git(root, "ls-tree", "-r", "--name-only", "-z", commit))


def working_files(root: Path) -> list[str]:
    """Every file in the working tree that git tracks or would track."""
    listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    return [p for p in _paths(listed) if (root / p).is_file()]


@contextmanager
def snapshot(root: Path, commit: str, folders: Sequence[str]) -> Iterator[Path]:
    """A temporary folder holding ``folders`` (and files) as they were in ``commit``.

    Raises:
        GitCommandError: ``git archive`` failed or wrote an unreadable archive.
    """
    with tempfile.TemporaryDirectory(prefix="pbi-validate-") as target:
        if folders:
            archive = _git(root, "archive", "--format=tar", commit, "--", *folders)
            try:
                with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                    tar.extractall(target, filter="data")
            except (tarfile.TarError, OSError) as exc:
                raise GitCommandError(f"could not unpack {commit}: {exc}") from exc
        yield Path(target)


def _paths(output: bytes) -> list[str]:
    try:
        return [p for p in output.decode("utf-8").split("\0") if p]
    except UnicodeDecodeError as exc:
        raise GitCommandError(f"git printed a path that is not UTF-8: {exc}") from exc


def _git(cwd: Path, *args: str) -> bytes:
    """Run ``git`` in ``cwd`` and return what it printed."""
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise GitUnavailableError("git is not installed or not on PATH") from exc
    except OSError as exc:
        raise GitCommandError(f"could not run git in {cwd}: {exc}") from exc
    if done.returncode != 0:
        message = done.stderr.decode(errors="replace").strip()
        raise GitCommandError(f"git {args[0]} failed: {message}")
    return done.stdout
