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


class RawLegacyReport(RawModel):
    """A report in the legacy format: one JSON document for the whole report.

    ``layout`` is ``<Name>.Report/report.json`` in a PBIP project saved
    without PBIR (``Report/Layout`` in ``.pbit`` and ``.pbix`` files). Its
    ``config`` and ``filters`` values are still JSON-encoded strings.
    """

    path: str
    layout: RawJsonFile


class RawTextFile(RawModel):
    """A text file, e.g. a ``.tmdl`` file. ``error`` is set if it was unreadable."""

    path: str
    text: str = ""
    error: str | None = None


class RawSemanticModel(RawModel):
    """A ``<Name>.SemanticModel`` folder.

    ``files`` are the ``.tmdl`` files of its ``definition`` folder. A model
    saved in the older TMSL format has none, and ``bim`` is its
    ``model.bim`` instead.
    """

    path: str
    files: tuple[RawTextFile, ...] = ()
    bim: RawJsonFile | None = None


class RawProject(RawModel):
    """A PBIP project: one report and, if referenced by path, its semantic model.

    ``model_missing`` says why there is no semantic model to read, if there
    is none.
    """

    name: str
    report: RawReport | RawLegacyReport
    semantic_model: RawSemanticModel | None = None
    model_missing: str | None = None
