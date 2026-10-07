from itertools import product

import pytest

from pbi_report_validator.diff.severity import (
    at_least,
    default_severity,
    with_severity,
)
from pbi_report_validator.domain.models import Category, ChangeKind, Finding, Severity
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES

C, K, S = Category, ChangeKind, Severity

# Every category and change combination the diff produces today.
EXPECTED = [
    (C.PAGE, K.ADDED, S.INFO),
    (C.PAGE, K.REMOVED, S.CRITICAL),
    (C.PAGE, K.RENAMED, S.INFO),
    (C.PAGE, K.REORDERED, S.INFO),
    (C.VISUAL, K.ADDED, S.INFO),
    (C.VISUAL, K.REMOVED, S.CRITICAL),
    (C.VISUAL, K.RENAMED, S.INFO),
    (C.VISUAL, K.RETYPED, S.WARNING),
    (C.VISUAL, K.MODIFIED, S.INFO),
    (C.VISUAL, K.MOVED, S.INFO),
    (C.FIELD, K.ADDED, S.WARNING),
    (C.FIELD, K.REMOVED, S.WARNING),
    (C.FIELD, K.MODIFIED, S.WARNING),
    (C.FILTER, K.ADDED, S.CRITICAL),
    (C.FILTER, K.REMOVED, S.CRITICAL),
    (C.FILTER, K.MODIFIED, S.CRITICAL),
    (C.SLICER, K.ADDED, S.CRITICAL),
    (C.SLICER, K.REMOVED, S.CRITICAL),
    (C.SLICER, K.MODIFIED, S.CRITICAL),
    (C.MEASURE, K.ADDED, S.INFO),
    (C.MEASURE, K.REMOVED, S.WARNING),
    (C.MEASURE, K.RENAMED, S.WARNING),
    (C.MEASURE, K.MODIFIED, S.CRITICAL),
    (C.PARSE_ISSUE, K.ERROR, S.WARNING),
    (C.DATA, K.ADDED, S.CRITICAL),
    (C.DATA, K.REMOVED, S.CRITICAL),
    (C.DATA, K.MODIFIED, S.CRITICAL),
    (C.DATA, K.ERROR, S.WARNING),
]


@pytest.mark.parametrize(("category", "change", "severity"), EXPECTED)
def test_default_severity(category: C, change: K, severity: S) -> None:
    assert default_severity(category, change) is severity


def test_every_combination_has_a_severity() -> None:
    for category, change in product(Category, ChangeKind):
        assert default_severity(category, change) in Severity


def test_with_severity_sets_default_and_keeps_the_rest() -> None:
    finding = Finding(
        category=C.FILTER, change=K.REMOVED, path="p/v/filters/f", message="gone"
    )

    [updated] = with_severity([finding])

    assert updated.severity is S.CRITICAL
    assert updated.model_copy(update={"severity": S.INFO}) == finding


def test_fixture_pair_has_every_severity() -> None:
    result = validate(FIXTURES / "sales_v1", FIXTURES / "sales_v2")

    assert {f.severity for f in result.findings} == set(Severity)
    assert result.severity_counts.model_dump() == {
        "critical": 3,
        "warning": 2,
        "info": 2,
    }


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [
        (S.INFO, [S.INFO, S.WARNING, S.CRITICAL]),
        (S.WARNING, [S.WARNING, S.CRITICAL]),
        (S.CRITICAL, [S.CRITICAL]),
    ],
)
def test_at_least(threshold: S, expected: list[S]) -> None:
    findings = [
        Finding(category=C.PAGE, change=K.ADDED, severity=s, path=s, message="m")
        for s in Severity
    ]

    assert [f.severity for f in at_least(findings, threshold)] == expected
