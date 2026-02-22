from fastapi.testclient import TestClient

from app.main import app


def test_detect_risky_text(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "false")
    client = TestClient(app)
    response = client.post(
        "/detect",
        json={"text": "Shocking internal source, share immediately before deleted."},
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
            "text": "Official statement with source and data, see https://example.com"
        },
    )
    body = response.json()
    assert response.status_code == 200
    assert body["label"] in {"credible", "suspicious"}
