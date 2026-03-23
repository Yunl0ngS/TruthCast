from app.services.url_extraction.extractors import (
    build_candidate,
    extract_with_readability,
    extract_with_trafilatura,
)


def test_build_candidate_computes_basic_metrics() -> None:
    candidate = build_candidate(
        extractor_name="readability",
        title="新闻标题",
        content="第一段内容。\n\n第二段内容。",
        html='<div><a href="/a">相关阅读</a></div>',
    )
    assert candidate.text_len > 0
    assert candidate.paragraph_count == 2
    assert candidate.chinese_ratio > 0


def test_extractors_return_candidates_for_article_html() -> None:
    html = """
    <html>
      <head><title>文章标题</title></head>
      <body>
        <article>
          <h1>文章标题</h1>
          <p>第一段正文，包含主要事实。</p>
          <p>第二段正文，补充细节。</p>
        </article>
      </body>
    </html>
    """
    readability_candidate = extract_with_readability(html)
    trafilatura_candidate = extract_with_trafilatura(html)
    assert readability_candidate is not None
    assert trafilatura_candidate is not None
    assert "第一段正文" in readability_candidate.content
    assert "第二段正文" in trafilatura_candidate.content
