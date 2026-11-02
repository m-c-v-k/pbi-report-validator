import json

import pytest

from pbi_report_validator.domain.models import (
    AiFinding,
    AiSuggestion,
    Category,
    ChangeKind,
    Severity,
)
from pbi_report_validator.matching.ai_match import (
    InvalidAiResponseError,
    MatchCandidates,
    build_match_prompt,
    match_candidates,
    match_response_schema,
    parse_suggestions,
)

C, K = Category, ChangeKind


def finding(category: Category, change: ChangeKind, path: str) -> AiFinding:
    return AiFinding(
        category=category,
        change=change,
        severity=Severity.INFO,
        path=path,
        message=f"{path} {change.value}",
    )


CANDIDATES = MatchCandidates(
    removed=(
        finding(C.MEASURE, K.REMOVED, "model/Sales/Margin %"),
        finding(C.VISUAL, K.REMOVED, "overview/card_old"),
    ),
    added=(
        finding(C.MEASURE, K.ADDED, "model/Sales/Gross Margin %"),
        finding(C.VISUAL, K.ADDED, "overview/card_new"),
    ),
)


def answer(*pairs: tuple[str, str], confidence: float = 0.9) -> str:
    suggestions = [
        {"old_path": o, "new_path": n, "confidence": confidence, "reason": "Same."}
        for o, n in pairs
    ]
    return json.dumps({"suggestions": suggestions})


def test_candidates_are_removed_and_added_pages_visuals_and_measures() -> None:
    findings = (
        finding(C.MEASURE, K.REMOVED, "model/Sales/A"),
        finding(C.MEASURE, K.MODIFIED, "model/Sales/B"),
        finding(C.FILTER, K.REMOVED, "p/v/filters/f"),
        finding(C.PAGE, K.ADDED, "trends"),
    )

    candidates = match_candidates(findings)

    assert [f.path for f in candidates.removed] == ["model/Sales/A"]
    assert [f.path for f in candidates.added] == ["trends"]
    assert not candidates.pairable


def test_pairable_needs_both_sides_in_one_category() -> None:
    assert CANDIDATES.pairable


def test_prompt_contains_the_candidates_as_json() -> None:
    system, prompt = build_match_prompt(CANDIDATES)

    assert "JSON only" in system
    sent = json.loads(prompt)
    assert [f["path"] for f in sent["removed"]] == [
        "model/Sales/Margin %",
        "overview/card_old",
    ]
    assert build_match_prompt(CANDIDATES) == (system, prompt)


def test_valid_pairs_become_suggestions() -> None:
    text = answer(("model/Sales/Margin %", "model/Sales/Gross Margin %"))

    assert parse_suggestions(text, CANDIDATES) == [
        AiSuggestion(
            category=C.MEASURE,
            old_path="model/Sales/Margin %",
            new_path="model/Sales/Gross Margin %",
            confidence=0.9,
            reason="Same.",
        )
    ]


@pytest.mark.parametrize(
    "pair",
    [
        ("model/Sales/Unknown", "model/Sales/Gross Margin %"),
        ("model/Sales/Margin %", "overview/card_new"),
        ("model/Sales/Gross Margin %", "model/Sales/Margin %"),
    ],
    ids=["unknown path", "other category", "reversed"],
)
def test_pairs_that_are_not_candidates_are_dropped(pair: tuple[str, str]) -> None:
    assert parse_suggestions(answer(pair), CANDIDATES) == []


def test_each_path_is_used_once() -> None:
    text = answer(
        ("overview/card_old", "overview/card_new"),
        ("overview/card_old", "overview/card_new"),
    )

    assert len(parse_suggestions(text, CANDIDATES)) == 1


def test_fenced_answer_with_extra_keys_and_wild_confidence_is_accepted() -> None:
    body = json.loads(answer(("overview/card_old", "overview/card_new"), confidence=7))
    body["suggestions"][0]["note"] = "ignored"
    text = f"Here you go:\n```json\n{json.dumps(body)}\n```"

    [suggestion] = parse_suggestions(text, CANDIDATES)

    assert suggestion.confidence == 1.0
    assert suggestion.source == "ai"


@pytest.mark.parametrize(
    "text",
    [
        "No idea.",
        '{"suggestions": [{"old_path": 1}]}',
        "{not json}",
        answer(("overview/card_old", "overview/card_new"), confidence=float("nan")),
    ],
    ids=["no json", "bad shape", "broken json", "nan confidence"],
)
def test_unusable_answer_raises(text: str) -> None:
    with pytest.raises(InvalidAiResponseError):
        parse_suggestions(text, CANDIDATES)


def test_response_schema_describes_the_parsed_shape() -> None:
    schema = match_response_schema()

    assert schema["type"] == "object"
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "suggestions" in properties
    answer = json.dumps(schema)
    for key in ("old_path", "new_path", "confidence", "reason"):
        assert f'"{key}"' in answer
