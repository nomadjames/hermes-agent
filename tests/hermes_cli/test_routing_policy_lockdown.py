from hermes_cli.routing_policy import (
    get_locked_main_model,
    get_locked_main_provider,
)


def test_locked_main_policy_constants():
    assert get_locked_main_model() == "gpt-5.4"
    assert get_locked_main_provider() == "openai-codex"


def test_gateway_model_is_locked():
    from gateway.run import _resolve_gateway_model

    assert _resolve_gateway_model({}) == "gpt-5.4"
