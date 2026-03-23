from app.services.url_extraction.metadata import extract_metadata


def test_extract_metadata_prefers_open_graph_title() -> None:
    html = """
    <html>
      <head>
        <meta property="og:title" content="OG 标题" />
        <meta property="article:published_time" content="2026-03-22T08:30:00+08:00" />
        <link rel="canonical" href="https://example.com/news/123" />
      </head>
      <body><h1>页面标题</h1></body>
    </html>
    """
    meta = extract_metadata(html, "https://example.com/raw")
    assert meta.title == "OG 标题"
    assert meta.publish_date == "2026-03-22"
    assert meta.canonical_url == "https://example.com/news/123"


def test_extract_metadata_falls_back_to_title_and_time_tag() -> None:
    html = """
    <html>
      <head><title>后备标题</title></head>
      <body><time datetime="2026-03-21T10:00:00+08:00"></time></body>
    </html>
    """
    meta = extract_metadata(html, "https://example.com/fallback")
    assert meta.title == "后备标题"
    assert meta.publish_date == "2026-03-21"
