"""Read-only git access, tested against temporary repositories."""

import subprocess
from pathlib import Path

import pytest

from pbi_report_validator.integrations import git as git_module
from pbi_report_validator.integrations.git import (
    GitCommandError,
    GitUnavailableError,
    NotARepositoryError,
    UnknownRefError,
    changed_files,
    files_at,
    repo_root,
    resolve_commit,
    snapshot,
    working_files,
)


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def write(repo: Path, path: str, text: str) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def commit(repo: Path) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with ``a/one.txt`` and ``b/two.txt``, tagged ``base``."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "core.autocrlf", "false")
    write(root, "a/one.txt", "one\n")
    write(root, "b/two.txt", "two\n")
    commit(root)
    git(root, "tag", "base")
    return root


def test_repo_root_from_a_subfolder(repo: Path) -> None:
    assert repo_root(repo / "a").resolve() == repo.resolve()


def test_repo_root_from_a_file(repo: Path) -> None:
    assert repo_root(repo / "a/one.txt").resolve() == repo.resolve()


def test_repo_root_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError):
        repo_root(tmp_path)


def test_resolve_commit_gives_the_commit_id(repo: Path) -> None:
    assert resolve_commit(repo, "base") == git(repo, "rev-parse", "HEAD").strip()


def test_unknown_ref_explains_how_to_fetch(repo: Path) -> None:
    with pytest.raises(UnknownRefError, match=r"git fetch origin missing.*fetch-depth"):
        resolve_commit(repo, "missing")


@pytest.mark.parametrize("ref", ["", "--output=x", "-h"])
def test_empty_or_option_like_ref_is_refused(repo: Path, ref: str) -> None:
    with pytest.raises(UnknownRefError):
        resolve_commit(repo, ref)


def test_changed_files_include_committed_uncommitted_and_untracked(
    repo: Path,
) -> None:
    write(repo, "a/one.txt", "changed\n")
    commit(repo)
    write(repo, "b/two.txt", "edited\n")
    write(repo, "c/new.txt", "new\n")
    write(repo, ".gitignore", "*.log\n")
    write(repo, "ignored.log", "x\n")

    changed = changed_files(repo, resolve_commit(repo, "base"))

    assert changed == [".gitignore", "a/one.txt", "b/two.txt", "c/new.txt"]


def test_changed_files_include_deleted_files(repo: Path) -> None:
    (repo / "b/two.txt").unlink()

    assert changed_files(repo, resolve_commit(repo, "base")) == ["b/two.txt"]


def test_files_at_lists_the_commit_not_the_working_tree(repo: Path) -> None:
    write(repo, "c/new.txt", "new\n")
    (repo / "a/one.txt").unlink()

    assert files_at(repo, resolve_commit(repo, "base")) == ["a/one.txt", "b/two.txt"]


def test_working_files_skip_deleted_and_ignored_files(repo: Path) -> None:
    (repo / "a/one.txt").unlink()
    write(repo, "c/new.txt", "new\n")
    write(repo, ".gitignore", "*.log\n")
    write(repo, "ignored.log", "x\n")

    assert sorted(working_files(repo)) == [".gitignore", "b/two.txt", "c/new.txt"]


def test_snapshot_exports_folders_as_they_were(repo: Path) -> None:
    base = resolve_commit(repo, "base")
    write(repo, "a/one.txt", "changed\n")
    commit(repo)

    with snapshot(repo, base, ["a"]) as folder:
        assert (folder / "a/one.txt").read_text(encoding="utf-8") == "one\n"
        assert not (folder / "b").exists()
        kept = folder

    assert not kept.exists()


def test_snapshot_without_folders_is_empty(repo: Path) -> None:
    with snapshot(repo, resolve_commit(repo, "base"), []) as folder:
        assert list(folder.iterdir()) == []


def test_snapshot_of_a_missing_folder_fails(repo: Path) -> None:
    with (
        pytest.raises(GitCommandError, match="git archive failed"),
        snapshot(repo, resolve_commit(repo, "base"), ["nope"]),
    ):
        pass


def test_git_not_installed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_module.subprocess, "run", missing)

    with pytest.raises(GitUnavailableError):
        resolve_commit(repo, "base")
