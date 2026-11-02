import json

import pytest

from pbi_report_validator.domain.models import AiFinding, Category, ChangeKind, Severity
from pbi_report_validator.reporting.ai_explain import (
    MAX_TEXT,
    InvalidAiExplanationError,
    build_explain_prompt,
    finding_ids,
    parse_explanations,
)

FINDINGS = (
    AiFinding(
        category=Category.FILTER,
        change=ChangeKind.REMOVED,
        severity=Severity.CRITICAL,
        path="overview/chart/filters/region",
        message="Filter on Region removed",
        old="Region in (Nordics)",
    ),
    AiFinding(
        category=Category.PAGE,
        change=ChangeKind.ADDED,
        severity=Severity.INFO,
        path="trends",
        message="Page 'Trends' added",
    ),
)


def answer(**texts: str) -> str:
    return json.dumps(
        {"explanations": [{"id": k, "text": v} for k, v in texts.items()]}
    )


def test_ids_follow_the_finding_order() -> None:
    assert finding_ids([4, 1]) == {"f1": 1, "f2": 4}


def test_prompt_sends_only_the_chosen_findings_with_their_ids() -> None:
    system, prompt = build_explain_prompt(FINDINGS, {"f1": 0})

    assert "JSON only" in system
    [sent] = json.loads(prompt)["findings"]
    assert sent["id"] == "f1"
    assert sent["path"] == "overview/chart/filters/region"
    assert sent["old"] == "Region in (Nordics)"


def test_explanations_map_back_to_finding_indices() -> None:
    text = answer(f1="  Totals now\n include Nordics. ", f9="unknown id")

    assert parse_explanations(text, {"f1": 0}) == {0: "Totals now include Nordics."}


def test_blank_and_repeated_explanations_are_dropped_and_long_ones_cut() -> None:
    body = {
        "explanations": [
            {"id": "f1", "text": "   "},
            {"id": "f2", "text": "x" * (MAX_TEXT + 50)},
            {"id": "f2", "text": "second"},
        ]
    }

    texts = parse_explanations(json.dumps(body), {"f1": 0, "f2": 1})

    assert texts == {1: "x" * (MAX_TEXT - 1) + "…"}


@pytest.mark.parametrize("text", ["Sorry.", '{"explanations": [{"id": 1}]}', "{broken"])
def test_unusable_answer_raises(text: str) -> None:
    with pytest.raises(InvalidAiExplanationError):
        parse_explanations(text, {"f1": 0})
