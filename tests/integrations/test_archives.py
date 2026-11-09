import zipfile
from pathlib import Path

import pytest

from pbi_report_validator.integrations.archives import (
    ArchiveLimits,
    ArchiveTooLargeError,
    InvalidArchiveError,
    UnsafeArchiveError,
    read_entries,
)
from tests.pbit import write_zip

WANTED = frozenset({"a", "b/c"})


def test_reads_only_the_wanted_entries(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"1", "b/c": b"2", "other": b"3"})

    assert read_entries(archive, WANTED) == {"a": b"1", "b/c": b"2"}


def test_missing_entries_are_left_out(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"1"})

    assert read_entries(archive, WANTED) == {"a": b"1"}


@pytest.mark.parametrize("content", [b"", b"PK", b"not a zip at all"])
def test_not_a_zip(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "x.zip"
    path.write_bytes(content)

    with pytest.raises(InvalidArchiveError, match="not a valid zip archive"):
        read_entries(path, WANTED)


def test_truncated_archive(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"x" * 10_000})
    data = archive.read_bytes()
    archive.write_bytes(data[: len(data) // 2])

    with pytest.raises(InvalidArchiveError):
        read_entries(archive, WANTED)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(InvalidArchiveError, match="could not read file"):
        read_entries(tmp_path / "missing.zip", WANTED)


@pytest.mark.parametrize(
    "name", ["../evil", "b/../../evil", "/etc/evil", r"..\evil", "C:/evil"]
)
def test_escaping_entry_names_are_refused(tmp_path: Path, name: str) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"1", name: b"2"})

    with pytest.raises(UnsafeArchiveError, match="points outside the archive"):
        read_entries(archive, WANTED)


def test_duplicate_wanted_entry_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "x.zip"
    with (
        pytest.warns(UserWarning, match="Duplicate name"),
        zipfile.ZipFile(path, "w") as archive,
    ):
        archive.writestr("a", b"1")
        archive.writestr("a", b"2")

    with pytest.raises(UnsafeArchiveError, match="appears twice"):
        read_entries(path, WANTED)


def test_entry_over_the_limit(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"x" * 101})

    with pytest.raises(ArchiveTooLargeError, match="'a' is larger than the 100"):
        read_entries(archive, WANTED, ArchiveLimits(entry_bytes=100))


def test_entries_together_over_the_total(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"x" * 60, "b/c": b"y" * 60})

    with pytest.raises(ArchiveTooLargeError, match="'b/c' is larger than the 40"):
        read_entries(archive, WANTED, ArchiveLimits(total_bytes=100))


def test_ignored_entries_do_not_count_towards_the_total(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {"a": b"1", "big": b"x" * 1000})

    assert read_entries(archive, WANTED, ArchiveLimits(total_bytes=10)) == {"a": b"1"}


def test_size_header_that_lies_is_refused(tmp_path: Path) -> None:
    path = write_zip(tmp_path / "x.zip", {"a": b"x" * 1000})
    _set_declared_size(path, "a", 10)

    with pytest.raises(InvalidArchiveError, match="Bad CRC-32"):
        read_entries(path, WANTED, ArchiveLimits(entry_bytes=100))


def test_too_many_entries(tmp_path: Path) -> None:
    archive = write_zip(tmp_path / "x.zip", {str(i): b"" for i in range(4)})

    with pytest.raises(ArchiveTooLargeError, match="4 entries"):
        read_entries(archive, WANTED, ArchiveLimits(entries=3))


def _set_declared_size(path: Path, name: str, size: int) -> None:
    """Rewrite the uncompressed size of ``name`` in both zip headers."""
    data = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo(name)
    true_size = info.file_size.to_bytes(4, "little")
    fake_size = size.to_bytes(4, "little")
    local_offset = info.header_offset + 22  # uncompressed size in local header
    assert data[local_offset : local_offset + 4] == true_size
    data[local_offset : local_offset + 4] = fake_size
    central = data.rfind(b"PK\x01\x02")
    assert data[central + 24 : central + 28] == true_size
    data[central + 24 : central + 28] = fake_size
    path.write_bytes(bytes(data))
