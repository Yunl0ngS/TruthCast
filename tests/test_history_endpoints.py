from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_history_flow() -> None:
    report_response = client.post(
        "/detect/report",
        json={"text": "官方通报称某指标为3%，并附来源链接。"},
    )
    assert report_response.status_code == 200

    list_response = client.get("/history")
    assert list_response.status_code == 200
    items = list_response.json()["items"]
    assert len(items) >= 1
    record_id = items[0]["id"]

    detail_response = client.get(f"/history/{record_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert "report" in detail
    assert "risk_label" in detail

    feedback_response = client.post(
        f"/history/{record_id}/feedback",
        json={"status": "inaccurate", "note": "测试反馈"},
    )
    assert feedback_response.status_code == 200
