"""E2E contract for installed-skill slash commands during busy sessions."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from gateway.session import build_session_key
from tests.e2e.conftest import make_event, send_and_capture


EXPANDED_CHECKPOINT = "expanded checkpoint workflow prompt"


@pytest.mark.asyncio
async def test_idle_installed_skill_expands_prompt_to_agent(
    adapter, runner, platform
):
    """Idle gateway dispatch resolves the profile skill before the agent turn."""
    with (
        patch(
            "agent.skill_commands.get_skill_commands",
            return_value={"/checkpoint": {"name": "checkpoint"}},
        ),
        patch(
            "agent.skill_commands.resolve_skill_command_key",
            return_value="/checkpoint",
        ),
        patch(
            "agent.skill_commands.build_skill_invocation_message",
            return_value=EXPANDED_CHECKPOINT,
        ),
    ):
        send = await send_and_capture(
            adapter, "/checkpoint active topic", platform
        )

    send.assert_called_once()
    runner._handle_message_with_agent.assert_awaited_once()
    routed_event = runner._handle_message_with_agent.await_args.args[0]
    assert routed_event.text == EXPANDED_CHECKPOINT


@pytest.mark.asyncio
async def test_busy_installed_skill_queues_expanded_prompt_without_interrupt(
    adapter, runner, platform
):
    """A busy skill invocation becomes one FIFO next turn and never interrupts."""
    event = make_event(platform, "/checkpoint active topic")
    adapter_session_key = build_session_key(
        event.source,
        group_sessions_per_user=adapter.config.extra.get(
            "group_sessions_per_user", True
        ),
        thread_sessions_per_user=adapter.config.extra.get(
            "thread_sessions_per_user", False
        ),
    )
    runner_session_key = runner._session_key_for_source(event.source)
    running_agent = MagicMock()
    adapter._active_sessions[adapter_session_key] = asyncio.Event()
    runner._running_agents[runner_session_key] = running_agent
    adapter.send.reset_mock()

    with (
        patch(
            "agent.skill_commands.resolve_skill_command_key",
            return_value="/checkpoint",
        ),
        patch(
            "agent.skill_commands.build_skill_invocation_message",
            return_value=EXPANDED_CHECKPOINT,
        ),
    ):
        await adapter.handle_message(event)
        await asyncio.sleep(0.3)

    adapter.send.assert_called_once()
    response_text = (
        adapter.send.call_args.kwargs.get("content")
        or adapter.send.call_args.args[1]
    )
    assert "Queued" in response_text
    assert "next turn" in response_text
    assert adapter._pending_messages[runner_session_key].text == EXPANDED_CHECKPOINT
    running_agent.interrupt.assert_not_called()
    runner._handle_message_with_agent.assert_not_awaited()


@pytest.mark.asyncio
async def test_busy_installed_skill_load_failure_is_reported_without_interrupt(
    adapter, runner, platform
):
    """A broken skill load must not silently drop the command or stop the run."""
    event = make_event(platform, "/checkpoint active topic")
    adapter_session_key = build_session_key(
        event.source,
        group_sessions_per_user=adapter.config.extra.get(
            "group_sessions_per_user", True
        ),
        thread_sessions_per_user=adapter.config.extra.get(
            "thread_sessions_per_user", False
        ),
    )
    runner_session_key = runner._session_key_for_source(event.source)
    running_agent = MagicMock()
    adapter._active_sessions[adapter_session_key] = asyncio.Event()
    runner._running_agents[runner_session_key] = running_agent
    adapter.send.reset_mock()

    with (
        patch(
            "agent.skill_commands.resolve_skill_command_key",
            return_value="/checkpoint",
        ),
        patch(
            "agent.skill_commands.build_skill_invocation_message",
            side_effect=RuntimeError("broken skill"),
        ),
    ):
        await adapter.handle_message(event)
        await asyncio.sleep(0.3)

    adapter.send.assert_called_once()
    response_text = (
        adapter.send.call_args.kwargs.get("content")
        or adapter.send.call_args.args[1]
    )
    assert response_text == "Failed to load skill for /checkpoint."
    assert runner_session_key not in adapter._pending_messages
    running_agent.interrupt.assert_not_called()
    runner._handle_message_with_agent.assert_not_awaited()