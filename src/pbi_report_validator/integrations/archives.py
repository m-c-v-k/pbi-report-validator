"""Read selected entries of a zip archive, such as a ``.pbit`` file, safely.

Archives are untrusted input. Only the entries asked for are read, and only
into memory; nothing is extracted to disk. An archive is refused when an
entry name could escape a target folder, when a wanted entry appears twice,
or when it holds too many entries or too many bytes. Sizes are counted while
decompressing, so a size header that lies does not get past the limits.
"""

import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from pbi_report_validator.integrations.errors import ProjectLoadError

MIB = 1024 * 1024
CHUNK_BYTES = MIB


@dataclass(frozen=True)
class ArchiveLimits:
    """The most an archive may hold: bytes per wanted entry, in total, entries."""

    entry_bytes: int = 256 * MIB
    total_bytes: int = 512 * MIB
    entries: int = 10_000


class ArchiveError(ProjectLoadError):
    """An archive could not be read safely."""


class InvalidArchiveError(ArchiveError):
    """The file is not a readable zip archive."""


class UnsafeArchiveError(ArchiveError):
    """An entry name escapes the archive, or a wanted entry appears twice."""


class ArchiveTooLargeError(ArchiveError):
    """The archive holds more entries or bytes than the limits allow."""


def read_entries(
    path: Path, names: frozenset[str], limits: ArchiveLimits | None = None
) -> dict[str, bytes]:
    """The contents of the entries in ``names`` that ``path`` holds.

    Args:
        path: The zip archive.
        names: The entry names to read; every other entry is ignored.
        limits: Size limits; the defaults when ``None``.

    Returns:
        The bytes of each wanted entry that is in the archive, by name.

    Raises:
        InvalidArchiveError: The file is not a zip archive, is corrupt, or
            uses encryption or an unsupported compression method.
        UnsafeArchiveError: An entry name escapes the archive, or a wanted
            entry appears more than once.
        ArchiveTooLargeError: Too many entries, or a wanted entry or all
            wanted entries together decompress to more bytes than allowed.
    """
    limits = limits or ArchiveLimits()
    try:
        with zipfile.ZipFile(path) as archive:
            wanted = _wanted_entries(path, archive.infolist(), names, limits)
            budget = limits.total_bytes
            contents: dict[str, bytes] = {}
            for info in wanted:
                data = _read_entry(path, archive, info, min(limits.entry_bytes, budget))
                contents[info.filename] = data
                budget -= len(data)
            return contents
    except (zipfile.BadZipFile, zlib.error, EOFError) as exc:
        raise InvalidArchiveError(f"{path}: not a valid zip archive ({exc})") from exc
    except (NotImplementedError, RuntimeError) as exc:
        raise InvalidArchiveError(f"{path}: cannot read archive ({exc})") from exc
    except OSError as exc:
        raise InvalidArchiveError(f"{path}: could not read file ({exc})") from exc


def _wanted_entries(
    path: Path,
    infos: list[zipfile.ZipInfo],
    names: frozenset[str],
    limits: ArchiveLimits,
) -> list[zipfile.ZipInfo]:
    """The entries in ``names``, after checking every entry of the archive."""
    if len(infos) > limits.entries:
        raise ArchiveTooLargeError(
            f"{path}: {len(infos)} entries (at most {limits.entries} allowed)"
        )
    for info in infos:
        if _escapes(info.filename):
            raise UnsafeArchiveError(
                f"{path}: entry {info.filename!r} points outside the archive"
            )
    wanted = [info for info in infos if info.filename in names]
    seen: set[str] = set()
    for info in wanted:
        if info.filename in seen:
            raise UnsafeArchiveError(f"{path}: entry {info.filename!r} appears twice")
        seen.add(info.filename)
    return sorted(wanted, key=lambda info: info.filename)


def _escapes(name: str) -> bool:
    """Whether an entry name is absolute or climbs out with ``..``."""
    normalised = PurePosixPath(name.replace("\\", "/"))
    has_drive = ":" in normalised.parts[0] if normalised.parts else False
    return normalised.is_absolute() or has_drive or ".." in normalised.parts


def _read_entry(
    path: Path, archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int
) -> bytes:
    """The entry's bytes, refusing more than ``limit`` of them."""
    if info.file_size > limit:
        raise _too_large(path, info.filename, limit)
    chunks: list[bytes] = []
    size = 0
    with archive.open(info) as entry:
        while chunk := entry.read(CHUNK_BYTES):
            size += len(chunk)
            if size > limit:
                raise _too_large(path, info.filename, limit)
            chunks.append(chunk)
    return b"".join(chunks)


def _too_large(path: Path, name: str, limit: int) -> ArchiveTooLargeError:
    return ArchiveTooLargeError(
        f"{path}: entry {name!r} is larger than the {limit} bytes allowed"
    )
