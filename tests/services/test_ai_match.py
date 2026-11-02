"""--ai-match end to end, with a recorded model answer instead of the API."""

import json
import shutil
from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.domain.models import AiMode, AiSettings, Category
from pbi_report_validator.integrations.anthropic_client import AiRateLimitError
from pbi_report_validator.matching.ai_match import match_response_schema
from pbi_report_validator.services.ai import InvalidAiOptionsError, ai_settings
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, REPO_ROOT

OLD = FIXTURES / "sales_v1"
SETTINGS = AiSettings(mode=AiMode.API, model="claude-opus-5-5", match=True)
RECORDED = json.dumps(
    {
        "suggestions": [
            {
                "old_path": "model/Sales/Margin %",
                "new_path": "model/Sales/Gross Margin %",
                "confidence": 0.85,
                "reason": "Same ratio of Amount and Cost under a clearer name.",
            }
        ]
    }
)


class RecordedLlm:
    """Answers every prompt with a fixed text and keeps the prompts."""

    def __init__(self, answer: str = RECORDED) -> None:
        self.answer = answer
        self.prompts: list[str] = []
        self.schemas: list[Mapping[str, object] | None] = []

    def complete(
        self, system: str, prompt: str, schema: Mapping[str, object] | None = None
    ) -> str:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return self.answer


class FailingLlm:
    def complete(
        self, system: str, prompt: str, schema: Mapping[str, object] | None = None
    ) -> str:
        raise AiRateLimitError("the Anthropic API rate limit was hit")


@pytest.fixture
def renamed_and_edited(tmp_path: Path) -> Path:
    """sales_v2 with Gross Margin % also edited, so only the AI can pair it."""
    new = shutil.copytree(FIXTURES / "sales_v2", tmp_path / "sales_v2")
    tmdl = new / "Sales.SemanticModel" / "definition" / "tables" / "Sales.tmdl"
    text = tmdl.read_text(encoding="utf-8")
    tmdl.write_text(
        text.replace("SUM(Sales[Cost]),", "SUM(Sales[Cost]) * 1,", 1), encoding="utf-8"
    )
    return new


def test_renamed_and_edited_measure_gets_a_suggestion(renamed_and_edited: Path) -> None:
    llm = RecordedLlm()

    result = validate(OLD, renamed_and_edited, ai=SETTINGS, llm=llm)

    [suggestion] = result.ai_suggestions
    assert (suggestion.old_path, suggestion.new_path) == (
        "model/Sales/Margin %",
        "model/Sales/Gross Margin %",
    )
    assert suggestion.category is Category.MEASURE
    assert "Margin %" in llm.prompts[0]
    assert llm.schemas == [match_response_schema()]


def test_suggestions_never_change_findings(renamed_and_edited: Path) -> None:
    plain = validate(
        OLD, renamed_and_edited, ai=SETTINGS.model_copy(update={"match": False})
    )

    matched = validate(OLD, renamed_and_edited, ai=SETTINGS, llm=RecordedLlm())

    assert matched.findings == plain.findings
    assert matched.severity_counts == plain.severity_counts


def test_nothing_to_pair_means_no_call() -> None:
    llm = RecordedLlm()

    result = validate(OLD, FIXTURES / "sales_v2", ai=SETTINGS, llm=llm)

    assert llm.prompts == []
    assert result.ai_suggestions == ()


def test_failed_call_becomes_an_info_finding(renamed_and_edited: Path) -> None:
    result = validate(OLD, renamed_and_edited, ai=SETTINGS, llm=FailingLlm())

    [ai] = [f for f in result.findings if f.category is Category.AI]
    assert ai.path == "ai/match"
    assert "rate limit" in ai.message
    assert result.ai_suggestions == ()


def test_unusable_answer_becomes_an_info_finding(renamed_and_edited: Path) -> None:
    result = validate(OLD, renamed_and_edited, ai=SETTINGS, llm=RecordedLlm("No."))

    assert any(f.path == "ai/match" for f in result.findings)


def test_ai_match_needs_ai_api() -> None:
    with pytest.raises(InvalidAiOptionsError, match="--ai-match needs --ai api"):
        ai_settings(AiMode.OFF, False, {}, match=True)


def test_cli_shows_the_suggestion_labelled(
    renamed_and_edited: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("PBI_VALIDATE_AI", raising=False)
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.llm_client", lambda ai, env: RecordedLlm()
    )
    markdown, data, html = (tmp_path / n for n in ("diff.md", "diff.json", "diff.html"))

    args = ["diff", str(OLD), str(renamed_and_edited), "--ai", "api", "--ai-match"]
    outputs = ["--markdown", str(markdown), "--json", str(data), "--html", str(html)]

    result = CliRunner().invoke(app, [*args, *outputs])

    assert result.exit_code == 0, result.output
    assert "AI-generated: probably renamed to model/Sales/Gross Margin %" in (
        markdown.read_text(encoding="utf-8").replace("\\", "")
    )
    [suggestion] = json.loads(data.read_text(encoding="utf-8"))["ai_suggestions"]
    assert suggestion["source"] == "ai"
    assert '<div class="ai-note">AI-generated: probably renamed from' in (
        html.read_text(encoding="utf-8")
    )
