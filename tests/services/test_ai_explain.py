"""--ai-explain end to end, with a fake model instead of the API."""

import json
from pathlib import Path
from typing import get_args

import pytest
from typer.testing import CliRunner

from pbi_report_validator.cli.main import app
from pbi_report_validator.domain.models import AiMode, AiSettings, Category, Severity
from pbi_report_validator.integrations.anthropic_client import AiServiceError
from pbi_report_validator.reporting.ai_payload import build_payload
from pbi_report_validator.services.ai import (
    MAX_EXPLAINED,
    InvalidAiOptionsError,
    ai_settings,
    with_explanations,
)
from pbi_report_validator.services.validate import validate
from tests.factories import FIXTURES, REPO_ROOT

OLD, NEW = FIXTURES / "sales_v1", FIXTURES / "sales_v2"
SETTINGS = AiSettings(mode=AiMode.API, model="claude-opus-5-5", explain=True)


class ExplainingLlm:
    """Explains every finding it is sent as "Explained <path>"."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, system: str, prompt: str) -> str:
        self.prompts.append(prompt)
        findings = json.loads(prompt)["findings"]
        return json.dumps(
            {
                "explanations": [
                    {"id": f["id"], "text": f"Explained {f['path']}"} for f in findings
                ]
            }
        )


class DownLlm:
    def complete(self, system: str, prompt: str) -> str:
        raise AiServiceError("the Anthropic API could not be reached")


def explained(settings: AiSettings = SETTINGS) -> dict[str, str]:
    result = validate(OLD, NEW, ai=settings, llm=ExplainingLlm())
    return {f.path: f.explanation.text for f in result.findings if f.explanation}


def test_warning_and_above_are_explained_by_default() -> None:
    result = validate(OLD, NEW, ai=SETTINGS, llm=ExplainingLlm())

    for finding in result.findings:
        expected = finding.severity is not Severity.INFO
        assert (finding.explanation is not None) == expected, finding.path
        if finding.explanation:
            assert finding.explanation.text == f"Explained {finding.path}"
            assert finding.explanation.source == "ai"


def test_threshold_is_configurable() -> None:
    every = explained(SETTINGS.model_copy(update={"explain_from": "info"}))
    critical = explained(SETTINGS.model_copy(update={"explain_from": "critical"}))

    assert len(every) == 7
    assert len(critical) == 3


def test_one_request_per_run_and_findings_unchanged() -> None:
    llm = ExplainingLlm()
    plain = validate(OLD, NEW)

    result = validate(OLD, NEW, ai=SETTINGS, llm=llm)

    assert len(llm.prompts) == 1
    without = tuple(f.model_copy(update={"explanation": None}) for f in result.findings)
    assert without == plain.findings
    assert result.severity_counts == plain.severity_counts


def test_at_most_max_explained_most_severe_first() -> None:
    result = validate(OLD, NEW)
    many = result.model_copy(update={"findings": result.findings * 20})
    llm = ExplainingLlm()

    with_explanations(many, llm, False, Severity.INFO)

    sent = json.loads(llm.prompts[0])["findings"]
    assert len(sent) == MAX_EXPLAINED
    # 60 critical findings exceed the cap, so no warning is sent.
    assert {f["severity"] for f in sent} == {"critical"}


def test_failed_call_becomes_an_info_finding() -> None:
    result = validate(OLD, NEW, ai=SETTINGS, llm=DownLlm())

    [ai] = [f for f in result.findings if f.category is Category.AI]
    assert (ai.path, ai.severity) == ("ai/explanations", Severity.INFO)
    assert not any(f.explanation for f in result.findings)


def test_ai_explain_needs_ai_api() -> None:
    with pytest.raises(InvalidAiOptionsError, match="--ai-explain needs --ai api"):
        ai_settings(AiMode.OFF, False, {}, explain_from=Severity.WARNING)


def test_explain_from_needs_ai_explain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)

    result = CliRunner().invoke(
        app, ["diff", str(OLD), str(NEW), "--ai-explain-from", "info"]
    )

    assert result.exit_code == 2
    assert "--ai-explain-from needs --ai-explain" in result.stderr


def test_cli_labels_explanations_in_all_three_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("PBI_VALIDATE_AI", raising=False)
    monkeypatch.setattr(
        "pbi_report_validator.cli.main.llm_client", lambda ai, env: ExplainingLlm()
    )
    paths = {ext: tmp_path / f"diff.{ext}" for ext in ("json", "md", "html")}
    outputs = ["--json", str(paths["json"]), "--markdown", str(paths["md"])]

    args = ["diff", str(OLD), str(NEW), "--ai", "api", "--ai-explain"]
    outputs += ["--html", str(paths["html"])]

    result = CliRunner().invoke(app, [*args, *outputs])

    assert result.exit_code == 0, result.output
    data = json.loads(paths["json"].read_text(encoding="utf-8"))
    explanations = [f["explanation"] for f in data["findings"] if "explanation" in f]
    assert explanations
    assert all(e["source"] == "ai" for e in explanations)
    markdown = paths["md"].read_text(encoding="utf-8").replace("\\", "")
    assert "_AI-generated: Explained " in markdown
    assert '<div class="ai-note">AI-generated: Explained ' in paths["html"].read_text(
        encoding="utf-8"
    )


def test_explain_from_values_match_the_severities() -> None:
    annotation = AiSettings.model_fields["explain_from"].annotation

    assert get_args(annotation) == tuple(s.value for s in Severity)


def test_payload_keeps_every_finding_in_order() -> None:
    result = validate(OLD, NEW)

    payload = build_payload(result, allow_data=False).findings

    assert [f.path for f in payload] == [f.path for f in result.findings]
