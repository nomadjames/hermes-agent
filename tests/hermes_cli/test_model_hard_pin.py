"""Regression tests for Hermes hard-pinning to GPT-5.4.

These tests intentionally lock the shared /model switch pipeline so future
refactors cannot quietly re-open runtime model switching.
"""

from unittest.mock import patch

from hermes_cli.model_switch import switch_model


_MOCK_VALIDATION = {"accepted": True, "persist": True, "recognized": True, "message": None}


def test_switch_model_rejects_non_pinned_model():
    result = switch_model(
        raw_input="deepseek-v3.2:cloud",
        current_provider="openai-codex",
        current_model="gpt-5.4",
    )

    assert result.success is False
    assert "hard-pinned to gpt-5.4" in result.error_message.lower()


def test_switch_model_rejects_non_pinned_provider():
    result = switch_model(
        raw_input="gpt-5.4",
        current_provider="openai-codex",
        current_model="gpt-5.4",
        explicit_provider="custom:ollama",
    )

    assert result.success is False
    assert "runtime model switching is disabled" in result.error_message.lower()


def test_switch_model_allows_reaffirming_pinned_model():
    with patch("hermes_cli.model_switch.resolve_alias", return_value=None), \
         patch("hermes_cli.model_switch.list_provider_models", return_value=[]), \
         patch("hermes_cli.runtime_provider.resolve_runtime_provider",
               return_value={"api_key": "***", "base_url": "https://chatgpt.com/backend-api/codex", "api_mode": "chat_completions"}), \
         patch("hermes_cli.models.validate_requested_model", return_value=_MOCK_VALIDATION), \
         patch("hermes_cli.model_switch.get_model_info", return_value=None), \
         patch("hermes_cli.model_switch.get_model_capabilities", return_value=None), \
         patch("hermes_cli.models.detect_provider_for_model", return_value=None):
        result = switch_model(
            raw_input="gpt-5.4",
            current_provider="openai-codex",
            current_model="gpt-5.4",
        )

    assert "hard-pinned" not in (result.error_message or "").lower()
