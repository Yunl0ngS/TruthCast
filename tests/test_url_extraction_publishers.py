from unittest.mock import MagicMock, patch

from app.services.url_extraction.publishers.ckxxapp import try_extract_ckxxapp_article
from app.services.url_extraction.publishers.cls import try_extract_cls_article
from app.services.url_extraction.publishers.thepaper import (
    try_extract_thepaper_article,
)


def test_try_extract_ckxxapp_article_extracts_mobile_article_fields() -> None:
    html = """
    <html>
      <head>
        <title>页面标题</title>
        <meta property="og:title" content="OG 标题" />
        <meta property="article:published_time" content="2026-03-22" />
      </head>
      <body>
        <div class="article-title">参考消息标题</div>
        <div class="article-time">2026-03-22 18:45:43</div>
        <script>
          var contentTxt ="<p>第一段正文。</p><p>第二段正文。</p>";
        </script>
      </body>
    </html>
    """
    result = try_extract_ckxxapp_article(
        "https://ckxxapp.ckxx.net/pages/2026/03/22/test.html",
        html,
    )

    assert result is not None
    assert result.title == "参考消息标题"
    assert result.publish_date == "2026-03-22"
    assert result.source_url == "https://ckxxapp.ckxx.net/pages/2026/03/22/test.html"
    assert result.content == "第一段正文。\n\n第二段正文。"
    assert result.comments == []


def test_try_extract_ckxxapp_article_returns_none_for_non_matching_url() -> None:
    html = "<html><body><div class='article-title'>标题</div></body></html>"
    result = try_extract_ckxxapp_article("https://example.com/news/1", html)
    assert result is None


def test_try_extract_ckxxapp_article_handles_realworld_escaped_contenttxt_without_garbled_text() -> None:
    html = """
    <html>
      <head>
        <meta property="article:published_time" content="2026-03-22" />
      </head>
      <body>
        <div class="article-title">高油价阴云压顶 外国投资者逃离日本股市</div>
        <div class="article-time">2026-03-22 18:45:43</div>
        <script>
          var contentTxt ="<p style=\\"text-indent: 2em; text-align: left;\\"><strong>参考消息网3月22日报道<\\/strong> 据彭博新闻社网站3月19日报道，石油风险导致前景黯淡之际，外国投资者逃离日本股市。<\\/p><p style=\\"text-indent: 2em; text-align: left;\\">由于越来越担忧油价上涨将打击日本经济，外国人上周成为日本股票的净卖家。<\\/p>";
        </script>
      </body>
    </html>
    """
    result = try_extract_ckxxapp_article(
        "https://ckxxapp.ckxx.net/pages/2026/03/22/test.html",
        html,
    )

    assert result is not None
    assert "参考消息网3月22日报道" in result.content
    assert "外国投资者逃离日本股市" in result.content
    assert "由于越来越担忧油价上涨将打击日本经济" in result.content
    assert "å" not in result.content
    assert "<\\/strong>" not in result.content
    assert result.comments == []


@patch("app.services.url_extraction.publishers.thepaper._fetch_thepaper_comments")
def test_try_extract_thepaper_article_extracts_next_data_fields(mock_fetch_comments) -> None:
    mock_fetch_comments.return_value = [
        {
            "userInfo": {"sname": "澎湃网友A"},
            "content": "评论一",
            "originCreateTime": "2026-03-23 10:00:00",
        }
    ]
    html = """
    <html>
      <head>
        <title>页面标题</title>
        <meta property="og:title" content="OG 标题" />
      </head>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {
              "pageProps": {
                "detailData": {
                  "contentDetail": {
                    "name": "澎湃标题",
                    "pubTime": "2026-03-23 09:30",
                    "content": "<p>第一段正文。</p><p>第二段正文。</p>"
                  }
                }
              }
            }
          }
        </script>
      </body>
    </html>
    """

    result = try_extract_thepaper_article(
        "https://www.thepaper.cn/newsDetail_forward_32810177",
        html,
    )

    assert result is not None
    assert result.title == "澎湃标题"
    assert result.publish_date == "2026-03-23"
    assert result.content == "第一段正文。\n\n第二段正文。"
    assert result.source_url == "https://www.thepaper.cn/newsDetail_forward_32810177"
    assert len(result.comments) == 1
    assert result.comments[0].username == "澎湃网友A"
    assert result.comments[0].content == "评论一"
    assert result.comments[0].publish_time == "2026-03-23 10:00:00"


@patch("app.services.url_extraction.publishers.cls._fetch_cls_comments")
def test_try_extract_cls_article_extracts_next_data_fields(mock_fetch_comments) -> None:
    mock_fetch_comments.return_value = [
        {
            "name": "小凯",
            "content": "评论二",
            "time": 1774231200,
        }
    ]
    html = """
    <html>
      <head>
        <title>页面标题</title>
      </head>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {
              "initialState": {
                "detail": {
                  "articleDetail": {
                    "title": "财联社标题",
                    "ctime": 1774195200,
                    "content": "<p>第一段正文。</p><p>第二段正文。</p>",
                    "commentNum": 43
                  },
                  "comment": {}
                }
              }
            }
          }
        </script>
      </body>
    </html>
    """

    result = try_extract_cls_article(
        "https://www.cls.cn/detail/2320263",
        html,
    )

    assert result is not None
    assert result.title == "财联社标题"
    assert result.publish_date == "2026-03-23"
    assert result.content == "第一段正文。\n\n第二段正文。"
    assert result.source_url == "https://www.cls.cn/detail/2320263"
    assert len(result.comments) == 1
    assert result.comments[0].username == "小凯"
    assert result.comments[0].content == "评论二"
    assert result.comments[0].publish_time == "2026-03-23 10:00:00"


@patch("app.services.url_extraction.publishers.cls._fetch_cls_comments")
def test_try_extract_cls_article_falls_back_to_dom_when_next_data_missing(mock_fetch_comments) -> None:
    mock_fetch_comments.return_value = []
    html = """
    <html>
      <head>
        <meta property="article:published_time" content="2026-03-23 11:22:33" />
      </head>
      <body>
        <div class="detail-title">DOM 财联社标题</div>
        <div class="detail-content"><p>DOM 第一段。</p><p>DOM 第二段。</p></div>
      </body>
    </html>
    """

    result = try_extract_cls_article(
        "https://www.cls.cn/detail/2320263",
        html,
    )

    assert result is not None
    assert result.title == "DOM 财联社标题"
    assert result.publish_date == "2026-03-23"
    assert result.content == "DOM 第一段。\n\nDOM 第二段。"
    assert result.comments == []
