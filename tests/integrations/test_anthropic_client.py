import pytest

from pbi_report_validator.integrations import anthropic_client
from pbi_report_validator.integrations.anthropic_client import (
    AiUnavailableError,
    ensure_available,
)


def test_installed_extra_is_available() -> None:
    ensure_available()


def test_missing_extra_is_reported_with_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(anthropic_client.importlib.util, "find_spec", lambda _: None)

    with pytest.raises(AiUnavailableError, match=r"pbi-report-validator\[ai\]"):
        ensure_available()
