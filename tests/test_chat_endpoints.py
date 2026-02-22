from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_chat_smoke_returns_actions() -> None:
    resp = client.post("/chat", json={"text": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "assistant_message" in body
    msg = body["assistant_message"]
    assert msg["role"] == "assistant"
    assert isinstance(msg.get("content"), str)
    assert isinstance(msg.get("actions"), list)
    assert len(msg["actions"]) >= 1


def test_chat_analyze_command_works() -> None:
    resp = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp.status_code == 200
    body = resp.json()
    msg = body["assistant_message"]
    assert "已完成一次全链路分析" in msg["content"]
    assert isinstance(msg.get("references"), list)
    actions = msg.get("actions") or []
    assert any((a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history ")) for a in actions)


def test_chat_stream_smoke_for_non_analyze_intent() -> None:
    # 避免触发真实全链路分析：短输入应直接返回 message + done
    with client.stream("POST", "/chat/stream", json={"text": "你好"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        assert "data: " in raw
        # 至少应包含 done 事件
        assert '"type":"done"' in raw or '"type": "done"' in raw

