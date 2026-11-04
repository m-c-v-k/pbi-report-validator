"""Base classes shared by all domain models."""

from pydantic import BaseModel, ConfigDict, Field


class DomainModel(BaseModel):
    """Base class: frozen, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceLocation(DomainModel):
    """Where an object is defined in a PBIP project.

    ``file`` is relative to the project folder, with forward slashes.
    ``pointer`` is an RFC 6901 JSON Pointer into a PBIR JSON file (``""``
    for the whole file), or for TMDL the object reference, e.g.
    ``table Sales / measure 'Total Sales'``.
    """

    file: str
    pointer: str


class Located(DomainModel):
    """A domain object that knows where it is defined.

    The location says where, not what: it is left out of equality, hashing
    and serialisation, so the same object read from another folder (a
    renamed project or a copy) still compares equal.
    """

    location: SourceLocation | None = Field(default=None, exclude=True, repr=False)

    def __eq__(self, other: object) -> bool:
        """Equal when every field but ``location`` (at any depth) is equal."""
        if not isinstance(other, Located) or type(other) is not type(self):
            return NotImplemented
        return self.model_dump() == other.model_dump()

    def __hash__(self) -> int:
        """A hash consistent with ``__eq__``."""
        return hash((type(self), self.model_dump_json()))
