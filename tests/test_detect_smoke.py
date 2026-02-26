from fastapi.testclient import TestClient

from app.main import app
from app.services import risk_snapshot


def test_detect_risky_text(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)
    response = client.post(
        "/detect",
        json={"text": "Shocking internal source, share immediately before deleted.", "force": True},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["label"] == "high_risk"
    assert isinstance(body["reasons"], list)


def test_detect_trust_text(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)
    response = client.post(
        "/detect",
        json={
            "text": "Official statement with source and data, see https://example.com",
            "force": True,
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["label"] in {"credible", "suspicious"}


def test_detect_non_news_blocks_before_risk_llm(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")

    monkeypatch.setattr(
        risk_snapshot,
        "analyze_text_meta",
        lambda text: ("simple", "非新闻文本", 3, False, 0.92, "chat", "闲聊语句"),
    )

    def _should_not_call(text: str):
        raise AssertionError("非新闻应在风险快照前被拦截，不应调用风险LLM")

    monkeypatch.setattr(risk_snapshot, "_detect_with_llm", _should_not_call)

    client = TestClient(app)
    response = client.post("/detect", json={"text": "你好呀，晚上吃了什么？"})
    body = response.json()
    assert response.status_code == 200
    assert body["strategy"]["is_news"] is False
    assert body["label"] == "needs_context"
