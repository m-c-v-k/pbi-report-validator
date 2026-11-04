"""Pure helpers for conventions shared by every layer.

Findings and reports locate visuals by a ``page/visual`` path and model
fields by a DAX-style ``Table[Name]`` key. Building and reading them here
keeps the format in one place.
"""

import re
from collections import Counter
from collections.abc import Callable, Sequence

from pbi_report_validator.domain.base import SourceLocation

PLAIN_TMDL_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def visual_path(page: str, visual: str) -> str:
    """The path of a visual, e.g. ``overview/card_total_sales``."""
    return f"{page}/{visual}"


def visual_path_of(path: str) -> str:
    """The ``page/visual`` a longer path starts with (or the path itself)."""
    return "/".join(path.split("/")[:2])


def is_within(path: str, parent: str) -> bool:
    """Whether ``path`` is ``parent`` or lies inside it."""
    return path == parent or path.startswith(f"{parent}/")


def field_key(table: str, name: str) -> str:
    """A DAX-style field key, e.g. ``Sales[Total Sales]``."""
    return f"{table}[{name}]"


def aggregated(key: str, aggregation: str | None) -> str:
    """A field key with its aggregation, e.g. ``Sum(Sales[Amount])``."""
    return f"{aggregation}({key})" if aggregation else key


def json_pointer(*parts: str | int) -> str:
    """An RFC 6901 JSON Pointer, e.g. ``/filterConfig/filters/0``."""
    escaped = (str(p).replace("~", "~0").replace("/", "~1") for p in parts)
    return "".join(f"/{part}" for part in escaped)


def json_location(file: str | None, *parts: str | int) -> SourceLocation | None:
    """The location of ``parts`` in a JSON ``file``; ``None`` without a file."""
    if file is None:
        return None
    return SourceLocation(file=file, pointer=json_pointer(*parts))


def tmdl_reference(table: str, measure: str) -> str:
    """A TMDL object reference, e.g. ``table Sales / measure 'Total Sales'``."""
    return f"table {_tmdl_name(table)} / measure {_tmdl_name(measure)}"


def _tmdl_name(name: str) -> str:
    """The name as TMDL writes it: quoted unless it is a plain identifier."""
    if PLAIN_TMDL_NAME.fullmatch(name):
        return name
    return "'" + name.replace("'", "''") + "'"


def field_name(key: str) -> str:
    """The name part of a field key: ``Sales[Margin %]`` -> ``Margin %``."""
    return key.partition("[")[2].removesuffix("]")


def unique_by[T](items: Sequence[T], key: Callable[[T], str]) -> dict[str, T]:
    """Items by key, leaving out every key that occurs more than once."""
    counts = Counter(key(item) for item in items)
    return {key(item): item for item in items if counts[key(item)] == 1}
