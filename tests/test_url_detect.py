import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from app.main import app

client = TestClient(app)

def test_url_detect_schema():
    """验证 /detect/url 接口的 Schema 响应（模拟爬虫成功场景）"""
    # 由于真实爬虫依赖网络和 LLM，我们在测试中可以使用 mock 或者只验证其存在性
    # 这里我们先验证接口是否存在且能处理请求
    response = client.post("/detect/url", json={"url": "https://example.com/news/123"})
    
    # 如果没有配置 API Key 或者网络不通，可能会返回 success=False，这是预期的
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "url" in data
    assert data["url"] == "https://example.com/news/123"

def test_url_detect_failure():
    """验证无效 URL 的处理"""
    response = client.post("/detect/url", json={"url": "not-a-url"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is False
    assert "error_msg" in data


def test_url_crawl_schema():
    """验证 /detect/url/crawl 接口存在且返回抓取响应结构"""
    response = client.post("/detect/url/crawl", json={"url": "https://example.com/news/123"})
    assert response.status_code == 200
    data = response.json()
    assert "success" in data
    assert "url" in data
    assert data["url"] == "https://example.com/news/123"


@patch("app.api.routes_detect.detect_risk_snapshot")
def test_url_risk_schema_validation(mock_risk):
    """验证 /detect/url/risk 接口存在且返回风险快照结构"""
    mock_risk.return_value = MagicMock(
        label="needs_review",
        confidence=0.7,
        score=60,
        reasons=["test"],
        strategy=None,
    )

    response = client.post(
        "/detect/url/risk",
        json={"url": "https://example.com/news/123", "title": "标题", "content": "正文"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["label"] == "needs_review"
    assert data["score"] == 60
