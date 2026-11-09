"""Build ``.pbit`` archives for tests from the synthetic sales fixtures.

A ``.pbit`` is a zip archive. Its report is ``Report/Layout`` (the legacy
format, UTF-16LE JSON) and its model is ``DataModelSchema`` (TMSL without
data, UTF-16LE JSON). The layout is taken from a ``*_legacy`` fixture and the
model schema is written from that fixture's TMDL model, so the archive holds
the same report and measures as the PBIP project. No binary fixtures are
committed; every archive is built in the test that needs it.
"""

import json
import zipfile
from pathlib import Path
from typing import Any

from pbi_report_validator.domain.models import SemanticModel
from pbi_report_validator.integrations.files import load_project
from pbi_report_validator.parsers.tmdl import parse_semantic_model

LAYOUT = "Report/Layout"
MODEL = "DataModelSchema"
# Entries a real .pbit also holds; the reader must ignore them.
OTHER_ENTRIES = {
    "Version": "1.28",
    "[Content_Types].xml": "<Types/>",
    "Settings": "{}",
    "Metadata": "{}",
}


def utf16(value: Any) -> bytes:
    """JSON as Power BI writes it into a .pbit: UTF-16LE without a BOM."""
    return json.dumps(value).encode("utf-16-le")


def pbit_entries(legacy_project: Path) -> dict[str, bytes]:
    """The entries of a .pbit with the report and model of ``legacy_project``."""
    layout = json.loads(
        (legacy_project / "Sales.Report/report.json").read_text(encoding="utf-8")
    )
    raw_model = load_project(legacy_project).semantic_model
    assert raw_model is not None
    entries = {name: text.encode("utf-16-le") for name, text in OTHER_ENTRIES.items()}
    entries[LAYOUT] = utf16(layout)
    entries[MODEL] = utf16(model_schema(parse_semantic_model(raw_model)))
    return entries


def model_schema(model: SemanticModel) -> dict[str, Any]:
    """A TMSL ``DataModelSchema`` with the tables, columns and measures."""
    tables = [
        {
            "name": table.name,
            "columns": [
                {"name": c.name, "dataType": c.data_type} for c in table.columns
            ],
            "measures": [
                {"name": m.name, "expression": m.expression.splitlines()}
                for m in table.measures
            ],
        }
        for table in model.tables
    ]
    return {"name": "Sales", "compatibilityLevel": 1567, "model": {"tables": tables}}


def write_zip(target: Path, entries: dict[str, bytes]) -> Path:
    """Write ``entries`` to a deflate-compressed zip archive at ``target``."""
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return target


def write_pbit(legacy_project: Path, target: Path) -> Path:
    """Write a .pbit with the report and model of ``legacy_project``."""
    return write_zip(target, pbit_entries(legacy_project))
