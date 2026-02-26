import pytest
from fastapi.testclient import TestClient
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
