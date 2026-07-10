"""Contract test for installed-skill active-session bypass."""

from unittest.mock import patch

from hermes_cli.commands import should_bypass_active_session


def test_installed_skill_command_bypasses_active_session_guard():
    """Known skill slashes must reach the runner instead of generic busy input."""
    with patch(
        "agent.skill_commands.resolve_skill_command_key",
        return_value="/checkpoint",
    ):
        assert should_bypass_active_session("checkpoint") is True
