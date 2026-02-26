from types import SimpleNamespace


def test_run_local_agent_repl_returns_false_without_api_key(monkeypatch):
    from app.cli import local_agent

    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "")

    handled = local_agent.run_local_agent_repl()
    assert handled is False


def test_repl_falls_back_to_chat_when_local_agent_unavailable(monkeypatch):
    from app.cli.commands import repl as repl_cmd

    called = {"chat": False, "session_id": None, "no_agent": None}

    monkeypatch.setattr(
        repl_cmd,
        "get_global_config",
        lambda: SimpleNamespace(local_agent=True),
    )
    monkeypatch.setattr(repl_cmd, "run_local_agent_repl", lambda: False)

    def _fake_chat(*, session_id=None, no_agent=False):
        called["chat"] = True
        called["session_id"] = session_id
        called["no_agent"] = no_agent

    monkeypatch.setattr(repl_cmd.chat, "chat", _fake_chat)

    repl_cmd.repl(session_id="chat_test_id")

    assert called["chat"] is True
    assert called["session_id"] == "chat_test_id"
    assert called["no_agent"] is False


def test_chat_with_local_agent_enabled_exits_when_handled(monkeypatch):
    from app.cli.commands import chat as chat_cmd

    monkeypatch.setattr(
        chat_cmd,
        "get_global_config",
        lambda: SimpleNamespace(local_agent=True, api_base="http://127.0.0.1:8000", timeout=30, retry_times=1),
    )

    # If local-agent handles successfully, chat should return before creating API client.
    monkeypatch.setattr("app.cli.local_agent.run_local_agent_repl", lambda: True)

    class _ShouldNotInit:
        def __init__(self, *args, **kwargs):
            raise AssertionError("APIClient should not be initialized when local-agent handles")

    monkeypatch.setattr(chat_cmd, "APIClient", _ShouldNotInit)

    chat_cmd.chat(session_id=None, no_agent=False)
