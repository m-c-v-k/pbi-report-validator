"""Pure helpers for conventions shared by every layer.

Findings and reports locate visuals by a ``page/visual`` path and model
fields by a DAX-style ``Table[Name]`` key. Building and reading them here
keeps the format in one place.
"""

from collections import Counter
from collections.abc import Callable, Sequence


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


def field_name(key: str) -> str:
    """The name part of a field key: ``Sales[Margin %]`` -> ``Margin %``."""
    return key.partition("[")[2].removesuffix("]")


def unique_by[T](items: Sequence[T], key: Callable[[T], str]) -> dict[str, T]:
    """Items by key, leaving out every key that occurs more than once."""
    counts = Counter(key(item) for item in items)
    return {key(item): item for item in items if counts[key(item)] == 1}
