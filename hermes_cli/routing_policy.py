"""Shared hard-pin routing policy for the main Hermes runtime."""

LOCKED_MAIN_MODEL = "gpt-5.4"
LOCKED_MAIN_PROVIDER = "openai-codex"
LOCKED_MAIN_BASE_URL = "https://chatgpt.com/backend-api/codex"


def get_locked_main_model() -> str:
    return LOCKED_MAIN_MODEL


def get_locked_main_provider() -> str:
    return LOCKED_MAIN_PROVIDER


def get_locked_main_base_url() -> str:
    return LOCKED_MAIN_BASE_URL
