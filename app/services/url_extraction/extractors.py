import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from readability import Document
import trafilatura


_NOISE_TERMS = [
    "相关阅读",
    "推荐阅读",
    "延伸阅读",
    "点击查看",
    "责任编辑",
    "来源：",
    "上一篇",
    "下一篇",
    "广告",
    "免责声明",
]


@dataclass
class ContentCandidate:
    extractor_name: str
    title: str
    content: str
    text_len: int
    paragraph_count: int
    link_density: float
    chinese_ratio: float
    noise_hits: list[str]
    raw_score: float = 0.0


def _clean_text(text: str | None) -> str:
    text = str(text or "")
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in text.splitlines()]
    return "\n\n".join([part for part in paragraphs if part])


def _count_paragraphs(content: str) -> int:
    return len([part for part in re.split(r"\n\s*\n", content) if part.strip()])


def _chinese_ratio(content: str) -> float:
    if not content:
        return 0.0
    chinese_chars = re.findall(r"[\u4e00-\u9fff]", content)
    return len(chinese_chars) / max(len(content), 1)


def _link_density(html: str) -> float:
    soup = BeautifulSoup(html or "", "html.parser")
    total_text = soup.get_text(" ", strip=True)
    link_text = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all("a"))
    if not total_text:
        return 0.0
    return min(len(link_text) / len(total_text), 1.0)


def build_candidate(extractor_name: str, title: str, content: str, html: str) -> ContentCandidate:
    cleaned_content = _clean_text(content)
    return ContentCandidate(
        extractor_name=extractor_name,
        title=_clean_text(title),
        content=cleaned_content,
        text_len=len(cleaned_content),
        paragraph_count=_count_paragraphs(cleaned_content),
        link_density=_link_density(html),
        chinese_ratio=_chinese_ratio(cleaned_content),
        noise_hits=[term for term in _NOISE_TERMS if term in cleaned_content],
    )


def extract_with_readability(html: str) -> ContentCandidate | None:
    document = Document(html or "")
    title = document.short_title()
    summary_html = document.summary(html_partial=True)
    soup = BeautifulSoup(summary_html, "html.parser")
    content = soup.get_text("\n\n", strip=True)
    candidate = build_candidate("readability", title, content, summary_html)
    return candidate if candidate.content else None


def extract_with_trafilatura(html: str) -> ContentCandidate | None:
    content = trafilatura.extract(html or "", output_format="txt", include_formatting=True) or ""
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.string if soup.title and soup.title.string else ""
    candidate = build_candidate("trafilatura", title, content, html)
    return candidate if candidate.content else None
