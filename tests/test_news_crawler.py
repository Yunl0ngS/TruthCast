import pytest
import httpx
from unittest.mock import MagicMock, patch
from app.services.news_crawler import crawl_news_url, _preprocess_html, CrawledNews

def test_preprocess_html():
    html = """
    <html>
        <head><title>Ignore Me</title></head>
        <body>
            <nav>Menu</nav>
            <article>
                <h1>Real Title</h1>
                <p>Real content here.</p>
                <script>alert('bad');</script>
                <style>.ads { display: none; }</style>
            </article>
            <footer>Contact Us</footer>
            <!-- Secret comment -->
        </body>
    </html>
    """
    cleaned = _preprocess_html(html)
    assert "Real Title" in cleaned
    assert "Real content here" in cleaned
    assert "<script>" not in cleaned
    assert "<style>" not in cleaned
    assert "<nav>" not in cleaned
    assert "<footer>" not in cleaned
    assert "Secret comment" not in cleaned

@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_success(mock_httpx_client):
    # Mock HTTP response for website content
    mock_resp_web = MagicMock()
    mock_resp_web.text = "<html><body><h1>News</h1><p>Content</p></body></html>"
    mock_resp_web.status_code = 200
    mock_resp_web.raise_for_status = MagicMock()

    # Mock HTTP response for LLM API
    mock_resp_llm = MagicMock()
    mock_resp_llm.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"title": "News Title", "content": "News Body", "publish_date": "2024-02-24"}'
                }
            }
        ]
    }
    mock_resp_llm.status_code = 200
    mock_resp_llm.raise_for_status = MagicMock()

    mock_client_instance = MagicMock()
    # First call is GET (website), second is POST (LLM)
    mock_client_instance.get.return_value = mock_resp_web
    mock_client_instance.post.return_value = mock_resp_llm
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance

    url = "https://example.com/news"
    # Ensure API Key is present for test
    with patch.dict("os.environ", {"TRUTHCAST_LLM_API_KEY": "test-key"}):
        result = crawl_news_url(url)

    assert result.success is True
    assert result.title == "News Title"
    assert result.content == "News Body"
    assert result.publish_date == "2024-02-24"
    assert result.source_url == url

@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_http_error(mock_httpx_client):
    mock_client_instance = MagicMock()
    mock_client_instance.get.side_effect = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=MagicMock())
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance
    
    url = "https://example.com/404"
    result = crawl_news_url(url)
    
    assert result.success is False
    assert "404" in result.error_msg
    assert result.source_url == url

@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_llm_error(mock_httpx_client):
    # Mock HTTP success for web
    mock_resp_web = MagicMock()
    mock_resp_web.text = "<html><body>Some News</body></html>"
    mock_resp_web.status_code = 200

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_resp_web
    # Mock LLM failure
    mock_client_instance.post.side_effect = Exception("LLM connection failed")
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance

    url = "https://example.com/news"
    with patch.dict("os.environ", {"TRUTHCAST_LLM_API_KEY": "test-key"}):
        result = crawl_news_url(url)

    assert result.success is False
    assert "LLM extraction failed" in result.error_msg
    assert result.content == "[提取失败]"
