import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from app.main import app
from app.schemas.detect import UrlDetectRequest, StrategyConfig

client = TestClient(app)

@patch("app.api.routes_detect.crawl_news_url")
@patch("app.api.routes_detect.detect_risk_snapshot")
def test_detect_url_endpoint(mock_risk, mock_crawl):
    # Mock crawl result
    mock_crawl.return_value = MagicMock(
        success=True,
        title="Test Title",
        content="Test Content",
        publish_date="2024-02-24",
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
    assert data["risk"]["label"] == "可疑"
    assert data["risk"]["score"] == 65

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
