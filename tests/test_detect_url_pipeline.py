from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.schemas.detect import StrategyConfig

client = TestClient(app)

@patch("app.api.routes_detect.crawl_news_url")
@patch("app.api.routes_detect.detect_risk_snapshot")
def test_detect_url_endpoint_compat(mock_risk, mock_crawl):
    mock_crawl.return_value = MagicMock(
        success=True,
        title="Test Title",
        content="Test Content",
        publish_date="2024-02-24",
        comments=[{"username": "用户A", "content": "评论A", "publish_time": "2024-02-24 10:00:00"}],
        error_msg=""
    )
    
    # Mock risk snapshot
    mock_risk.return_value = MagicMock(
        label="可疑",
        confidence=0.8,
        score=65,
        reasons=["Reason 1"],
        strategy=StrategyConfig(max_claims=5)
    )
    
    response = client.post(
        "/detect/url",
        json={"url": "https://example.com/test"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["title"] == "Test Title"
    assert data["content"] == "Test Content"
    assert data["comments"][0]["username"] == "用户A"
    assert data["risk"]["label"] == "可疑"
    assert data["risk"]["score"] == 65
    mock_risk.assert_called_once_with("Test Title\n\nTest Content", enable_news_gate=True)


@patch("app.api.routes_detect.crawl_news_url")
def test_detect_url_crawl_endpoint_returns_content_without_risk(mock_crawl):
    mock_crawl.return_value = MagicMock(
        success=True,
        title="Test Title",
        content="Test Content",
        publish_date="2024-02-24",
        comments=[{"username": "用户A", "content": "评论A", "publish_time": "2024-02-24 10:00:00"}],
        error_msg=""
    )

    with patch("app.api.routes_detect.detect_risk_snapshot") as mock_risk:
        response = client.post(
            "/detect/url/crawl",
            json={"url": "https://example.com/test-crawl"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["title"] == "Test Title"
    assert data["content"] == "Test Content"
    assert data["comments"][0]["content"] == "评论A"
    mock_risk.assert_not_called()


@patch("app.api.routes_detect.detect_risk_snapshot")
def test_detect_url_risk_endpoint(mock_risk):
    mock_risk.return_value = MagicMock(
        label="可疑",
        confidence=0.8,
        score=65,
        reasons=["Reason 1"],
        strategy=StrategyConfig(max_claims=5)
    )

    response = client.post(
        "/detect/url/risk",
        json={
            "url": "https://example.com/test-risk",
            "title": "Test Title",
            "content": "Test Content",
        }
    )

    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "可疑"
    assert data["score"] == 65
    mock_risk.assert_called_once_with("Test Title\n\nTest Content", enable_news_gate=True)


@patch("app.api.routes_detect.crawl_news_url")
@patch("app.api.routes_detect.detect_risk_snapshot")
def test_detect_url_endpoint_logs_summary(mock_risk, mock_crawl):
    mock_crawl.return_value = MagicMock(
        success=True,
        title="Test Title",
        content="Test Content",
        publish_date="2024-02-24",
        comments=[],
        error_msg=""
    )
    mock_risk.return_value = MagicMock(
        label="可疑",
        confidence=0.8,
        score=65,
        reasons=["Reason 1"],
        strategy=StrategyConfig(max_claims=5)
    )

    with patch("app.api.routes_detect.logger.info") as mock_info:
        response = client.post(
            "/detect/url",
            json={"url": "https://example.com/test-log"}
        )

    assert response.status_code == 200
    logged = " | ".join(str(call) for call in mock_info.call_args_list)
    assert "链接核查：收到 URL 抓取请求" in logged
    assert "链接核查：抓取成功" in logged
    assert "链接核查：风险快照完成" in logged

@patch("app.api.routes_detect.crawl_news_url")
def test_detect_url_crawl_fail(mock_crawl):
    mock_crawl.return_value = MagicMock(
        success=False,
        error_msg="404 Not Found"
    )
    
    response = client.post(
        "/detect/url",
        json={"url": "https://example.com/fail"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "404" in data["error_msg"]
