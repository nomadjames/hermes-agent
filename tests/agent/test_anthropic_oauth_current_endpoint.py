from urllib.parse import parse_qs, urlparse


def test_hermes_anthropic_oauth_uses_current_claude_authorization_surface(
    monkeypatch, capsys
):
    from agent import anthropic_adapter as mod

    monkeypatch.setattr("builtins.input", lambda _prompt: "")
    monkeypatch.setattr("webbrowser.open", lambda *_args, **_kwargs: False)

    assert mod.run_hermes_oauth_login_pure() is None

    output = capsys.readouterr().out
    auth_url = next(
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("https://")
    )
    parsed = urlparse(auth_url)
    params = parse_qs(parsed.query)

    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "claude.com",
        "/cai/oauth/authorize",
    )
    assert params["redirect_uri"] == [
        "https://platform.claude.com/oauth/code/callback"
    ]
    assert params["code_challenge_method"] == ["S256"]
    assert params["state"][0]
    assert params["code_challenge"][0]
    assert set(params["scope"][0].split()) == {
        "org:create_api_key",
        "user:profile",
        "user:inference",
        "user:sessions:claude_code",
        "user:mcp_servers",
        "user:file_upload",
    }
