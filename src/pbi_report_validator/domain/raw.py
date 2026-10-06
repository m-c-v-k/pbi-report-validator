"""Raw contents of a PBIP project, as read from disk and before parsing.

These models are the hand-over point between ``integrations`` (which reads
files) and ``parsers`` (which interpret them). JSON stays untyped here; the
parsers turn it into the typed domain models. The models are frozen, but the
JSON dictionaries inside them are not; parsers must not modify them.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict

JsonObject = dict[str, Any]


class RawModel(BaseModel):
    """Base class: frozen, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RawJsonFile(RawModel):
    """A JSON file. ``error`` is set (and ``content`` empty) if it was invalid."""

    path: str
    content: JsonObject = {}
    error: str | None = None


class RawPage(RawModel):
    """A page folder: its ``page.json`` and the ``visual.json`` of each visual."""

    name: str
    page: RawJsonFile
    visuals: tuple[RawJsonFile, ...] = ()


class RawReport(RawModel):
    """The ``<Name>.Report/definition`` folder."""

    path: str
    report: RawJsonFile
    pages_meta: RawJsonFile | None = None
    pages: tuple[RawPage, ...] = ()


class RawTextFile(RawModel):
    """A text file, e.g. a ``.tmdl`` file."""

    path: str
    text: str


class RawSemanticModel(RawModel):
    """The ``.tmdl`` files of a ``<Name>.SemanticModel/definition`` folder."""

    path: str
    files: tuple[RawTextFile, ...] = ()


class RawProject(RawModel):
    """A PBIP project: one report and, if referenced by path, its semantic model."""

    name: str
    report: RawReport
    semantic_model: RawSemanticModel | None = None
