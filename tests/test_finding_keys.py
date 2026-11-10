"""Finding keys: unique in every fixture comparison and stable across runs."""

from collections.abc import Callable
from pathlib import Path

import pytest

from pbi_report_validator.domain.models import (
    Category,
    ChangeKind,
    DiffResult,
    Finding,
    Severity,
)
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, SNAPSHOTS
from tests.integrations.test_recorded_powerbi import recorded_run
from tests.pbit import write_pbit

SNAPSHOT = SNAPSHOTS / "finding_keys.txt"
PAIRS = [
    ("sales_v1", "sales_v2"),
    ("sales_v2", "sales_v1"),
    ("sales_v2", "sales_v3"),
    ("sales_v1", "sales_v3"),
    ("sales_v1_legacy", "sales_v2_legacy"),
]


def runs(tmp_path: Path) -> dict[str, Callable[[], DiffResult]]:
    """Every fixture comparison, by a readable name."""
    named: dict[str, Callable[[], DiffResult]] = {
        f"{old} -> {new}": lambda o=old, n=new: validate(FIXTURES / o, FIXTURES / n)
        for old, new in PAIRS
    }
    old = write_pbit(FIXTURES / "sales_v1_legacy", tmp_path / "v1.pbit")
    new = write_pbit(FIXTURES / "sales_v2_legacy", tmp_path / "v2.pbit")
    named["v1.pbit -> v2.pbit"] = lambda: validate(old, new)
    named["sales_v1 -> sales_v2 --data (recorded)"] = recorded_run
    return named


def keys_text(tmp_path: Path) -> str:
    sections = []
    for name, run in runs(tmp_path).items():
        keys = "\n".join(f.key for f in run().findings)
        sections.append(f"# {name}\n{keys}\n")
    return "\n".join(sections)


def test_keys_match_snapshot(tmp_path: Path) -> None:
    assert keys_text(tmp_path) == SNAPSHOT.read_text(encoding="utf-8")


def test_keys_are_unique_and_stable(tmp_path: Path) -> None:
    for name, run in runs(tmp_path).items():
        first, second = run(), run()
        keys = [f.key for f in first.findings]
        assert len(set(keys)) == len(keys), name
        assert keys == [f.key for f in second.findings], name


def test_pbit_and_legacy_keys_equal_the_pbir_keys(tmp_path: Path) -> None:
    named = runs(tmp_path)
    pbir = [f.key for f in named["sales_v1 -> sales_v2"]().findings]

    assert [f.key for f in named["v1.pbit -> v2.pbit"]().findings] == pbir
    assert [
        f.key for f in named["sales_v1_legacy -> sales_v2_legacy"]().findings
    ] == pbir


def finding(path: str, message: str = "m") -> Finding:
    return Finding(
        category=Category.PARSE_ISSUE,
        change=ChangeKind.ERROR,
        severity=Severity.WARNING,
        path=path,
        message=message,
    )


@pytest.mark.parametrize("extra", ["a/first", "z/last", "new/report.json"])
def test_unrelated_findings_do_not_change_keys(extra: str) -> None:
    findings = (finding("new/report.json", "x"), finding("new/model.bim"))
    before = DiffResult(old_source="o", new_source="n", findings=findings)
    after = DiffResult(
        old_source="o", new_source="n", findings=(finding(extra, "y"), *findings)
    )

    keys_after = {f.message + f.path: f.key for f in after.findings}
    for f in before.findings:
        assert keys_after[f.message + f.path] == f.key


def test_keys_ignore_message_severity_and_explanation() -> None:
    one = finding("new/report.json", "one")
    other = one.model_copy(update={"message": "other", "severity": Severity.INFO})

    keys = [
        DiffResult(old_source="o", new_source="n", findings=(f,)).findings[0].key
        for f in (one, other)
    ]

    assert keys == ["parse:parse_issue:error:new/report.json"] * 2
