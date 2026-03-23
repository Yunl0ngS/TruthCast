from app.services.url_extraction.publishers.ckxxapp import (
    PublisherArticleResult,
    try_extract_ckxxapp_article,
)
from app.services.url_extraction.publishers.cls import try_extract_cls_article
from app.services.url_extraction.publishers.thepaper import (
    try_extract_thepaper_article,
)


def try_extract_publisher_article(source_url: str, html: str) -> PublisherArticleResult | None:
    for extractor in (
        try_extract_ckxxapp_article,
        try_extract_thepaper_article,
        try_extract_cls_article,
    ):
        result = extractor(source_url, html)
        if result is not None:
            return result
    return None
