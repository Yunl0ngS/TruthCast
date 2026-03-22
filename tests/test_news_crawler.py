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

@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_success(mock_httpx_client, _mock_validate_url):
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

@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_http_error(mock_httpx_client, _mock_validate_url):
    mock_client_instance = MagicMock()
    mock_client_instance.get.side_effect = httpx.HTTPStatusError("404 Not Found", request=MagicMock(), response=MagicMock())
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance
    
    url = "https://example.com/404"
    result = crawl_news_url(url)
    
    assert result.success is False
    assert "404" in result.error_msg
    assert result.source_url == url

@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_llm_error(mock_httpx_client, _mock_validate_url):
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


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_logs_fetch_summary(mock_httpx_client, _mock_validate_url):
    mock_resp_web = MagicMock()
    mock_resp_web.text = "<html><body><h1>News</h1><p>Content</p></body></html>"
    mock_resp_web.status_code = 200
    mock_resp_web.raise_for_status = MagicMock()

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
    mock_client_instance.get.return_value = mock_resp_web
    mock_client_instance.post.return_value = mock_resp_llm
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance

    url = "https://example.com/news"
    with patch.dict("os.environ", {"TRUTHCAST_LLM_API_KEY": "test-key"}):
        with patch("app.services.news_crawler.logger.info") as mock_info:
            result = crawl_news_url(url)

    assert result.success is True
    logged = " | ".join(str(call) for call in mock_info.call_args_list)
    assert "开始抓取新闻链接" in logged
    assert "HTTP获取成功" in logged
    assert "提取成功" in logged


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_retries_llm_timeout_then_succeeds(mock_httpx_client, _mock_validate_url):
    mock_resp_web = MagicMock()
    mock_resp_web.text = "<html><body><h1>News</h1><p>Content</p></body></html>"
    mock_resp_web.status_code = 200
    mock_resp_web.raise_for_status = MagicMock()

    mock_resp_llm = MagicMock()
    mock_resp_llm.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"title": "Retry Title", "content": "Retry Body", "publish_date": "2024-02-24"}'
                }
            }
        ]
    }
    mock_resp_llm.status_code = 200
    mock_resp_llm.raise_for_status = MagicMock()

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_resp_web
    mock_client_instance.post.side_effect = [httpx.ReadTimeout("The read operation timed out"), mock_resp_llm]
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance

    url = "https://example.com/retry-news"
    env = {
        "TRUTHCAST_LLM_API_KEY": "test-key",
        "TRUTHCAST_CRAWLER_LLM_MAX_RETRIES": "2",
        "TRUTHCAST_CRAWLER_LLM_RETRY_DELAY_SEC": "0",
    }
    with patch.dict("os.environ", env):
        result = crawl_news_url(url)

    assert result.success is True
    assert result.title == "Retry Title"
    assert mock_client_instance.post.call_count == 2


@patch("app.core.security.validate_url_for_ssrf", side_effect=lambda url: url)
@patch("app.services.news_crawler.httpx.Client")
def test_crawl_news_url_uses_configured_llm_timeout(mock_httpx_client, _mock_validate_url):
    mock_resp_web = MagicMock()
    mock_resp_web.text = "<html><body><h1>News</h1><p>Content</p></body></html>"
    mock_resp_web.status_code = 200
    mock_resp_web.raise_for_status = MagicMock()

    mock_resp_llm = MagicMock()
    mock_resp_llm.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": '{"title": "Timed Title", "content": "Timed Body", "publish_date": "2024-02-24"}'
                }
            }
        ]
    }
    mock_resp_llm.status_code = 200
    mock_resp_llm.raise_for_status = MagicMock()

    mock_client_instance = MagicMock()
    mock_client_instance.get.return_value = mock_resp_web
    mock_client_instance.post.return_value = mock_resp_llm
    mock_client_instance.__enter__.return_value = mock_client_instance
    mock_httpx_client.return_value = mock_client_instance

    url = "https://example.com/timed-news"
    env = {
        "TRUTHCAST_LLM_API_KEY": "test-key",
        "TRUTHCAST_CRAWLER_LLM_TIMEOUT_SEC": "45",
        "TRUTHCAST_CRAWLER_LLM_READ_TIMEOUT_SEC": "50",
    }
    with patch.dict("os.environ", env):
        result = crawl_news_url(url)

    assert result.success is True
    _, kwargs = mock_httpx_client.call_args
    timeout = kwargs["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 45
    assert timeout.read == 50
