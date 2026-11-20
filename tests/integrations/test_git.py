"""Read-only git access, tested against temporary repositories."""

import subprocess
from pathlib import Path

import pytest

from pbi_report_validator.integrations import git as git_module
from pbi_report_validator.integrations.archives import ArchiveLimits
from pbi_report_validator.integrations.git import (
    GitCommandError,
    GitTimeoutError,
    GitUnavailableError,
    NotARepositoryError,
    SnapshotTooLargeError,
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


def test_snapshot_of_a_missing_folder_is_empty(repo: Path) -> None:
    with snapshot(repo, resolve_commit(repo, "base"), ["nope"]) as folder:
        assert list(folder.iterdir()) == []


def test_snapshot_ignores_export_attributes(repo: Path) -> None:
    write(repo, ".gitattributes", "a/one.txt export-ignore\nb/* export-subst\n")
    write(repo, "b/two.txt", "$Format:%H$\n")
    head = commit(repo)

    with snapshot(repo, head, ["a", "b"]) as folder:
        assert (folder / "a/one.txt").read_text(encoding="utf-8") == "one\n"
        assert (folder / "b/two.txt").read_text(encoding="utf-8") == "$Format:%H$\n"


def test_snapshot_treats_folder_names_literally(repo: Path) -> None:
    write(repo, "[ab]/file.txt", "literal\n")
    head = commit(repo)

    # As a wildcard, "[ab]" would also match the folders "a" and "b".
    with snapshot(repo, head, ["[ab]"]) as folder:
        assert [p.name for p in folder.iterdir()] == ["[ab]"]


def test_snapshot_leaves_out_symbolic_links(repo: Path) -> None:
    blob = git(repo, "hash-object", "-w", "a/one.txt").strip()
    git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},a/link")
    git(repo, "commit", "-q", "-m", "link")

    with snapshot(repo, resolve_commit(repo, "HEAD"), ["a"]) as folder:
        assert sorted(p.name for p in (folder / "a").iterdir()) == ["one.txt"]


@pytest.mark.parametrize(
    "limits",
    [
        ArchiveLimits(entry_bytes=3),
        ArchiveLimits(total_bytes=6),
        ArchiveLimits(entries=1),
    ],
)
def test_snapshot_over_the_limits_is_refused(repo: Path, limits: ArchiveLimits) -> None:
    with (
        pytest.raises(SnapshotTooLargeError),
        snapshot(repo, resolve_commit(repo, "base"), ["a", "b"], limits),
    ):
        pass


def test_listing_works_from_a_subfolder(repo: Path) -> None:
    write(repo, "c/new.txt", "new\n")
    base = resolve_commit(repo, "base")

    assert changed_files(repo / "a", base) == ["c/new.txt"]
    assert sorted(working_files(repo / "a")) == ["a/one.txt", "b/two.txt", "c/new.txt"]
    assert files_at(repo / "a", base) == ["a/one.txt", "b/two.txt"]


def test_path_that_is_not_utf8_is_an_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(git_module, "_git", lambda *args, **kwargs: b"\xff\0")

    with pytest.raises(GitCommandError, match="not UTF-8"):
        files_at(repo, "base")


def test_repo_root_keeps_other_git_errors(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dubious(*args: object, **kwargs: object) -> bytes:
        raise GitCommandError("git rev-parse failed: fatal: detected dubious ownership")

    monkeypatch.setattr(git_module, "_git", dubious)

    with pytest.raises(GitCommandError, match="dubious ownership") as raised:
        repo_root(repo)
    assert not isinstance(raised.value, NotARepositoryError)


def test_repo_root_of_a_missing_folder(tmp_path: Path) -> None:
    with pytest.raises(NotARepositoryError, match="does not exist"):
        repo_root(tmp_path / "missing" / "deeper")


def test_git_not_installed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(git_module.subprocess, "run", missing)

    with pytest.raises(GitUnavailableError):
        resolve_commit(repo, "base")


def test_git_that_hangs_times_out(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("git", 1)

    monkeypatch.setattr(git_module.subprocess, "run", hang)

    with pytest.raises(GitTimeoutError, match="took over"):
        resolve_commit(repo, "base")
