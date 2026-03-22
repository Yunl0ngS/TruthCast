from app.services.url_extraction.rendered import render_page


def test_render_page_returns_rendered_html(monkeypatch) -> None:
    class FakePage:
        url = "https://example.com/news"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            assert url == "https://example.com/news"
            assert wait_until == "networkidle"
            assert timeout == 20000

        def content(self) -> str:
            return "<html><body><article>渲染正文</article></body></html>"

    class FakeBrowser:
        def new_page(self) -> FakePage:
            return FakePage()

        def close(self) -> None:
            return None

    class FakeChromium:
        def launch(self, headless: bool = True) -> FakeBrowser:
            assert headless is True
            return FakeBrowser()

    class FakeManager:
        chromium = FakeChromium()

        def __enter__(self) -> "FakeManager":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.services.url_extraction.rendered.sync_playwright", lambda: FakeManager())

    result = render_page("https://example.com/news")
    assert result.success is True
    assert result.final_url == "https://example.com/news"
    assert "<article>" in result.html


def test_render_page_returns_failed_result_when_browser_errors(monkeypatch) -> None:
    class FakeManager:
        def __enter__(self) -> "FakeManager":
            raise RuntimeError("browser missing")

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr("app.services.url_extraction.rendered.sync_playwright", lambda: FakeManager())

    result = render_page("https://example.com/fail")
    assert result.success is False
    assert "browser missing" in result.error_msg
