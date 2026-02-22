import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


KB_PATH = Path("data/kb/authority_evidence.json")

SCENARIO_KEYWORDS: dict[str, list[str]] = {
    "health": ["health", "vaccine", "infection", "outbreak", "医院", "疫苗", "疫情", "感染率", "卫健"],
    "governance": ["government", "policy", "official", "政务", "通报", "公告", "网信办", "治理"],
    "security": ["security", "fraud", "crime", "公安", "网安", "诈骗", "安全"],
    "media": ["rumor", "fact-check", "media", "谣言", "辟谣", "断章取义", "旧闻"],
    "technology": ["app", "platform", "ai", "芯片", "算力", "平台", "工信"],
    "education": ["school", "student", "campus", "教育", "校园", "大学生"],
}


@dataclass
class KBEvidence:
    entry_id: str
    title: str
    source: str
    url: str
    published_at: str
    summary: str
    tags: list[str]
    domains: list[str]
    stance_hint: str
    credibility: float


def _tokenize(text: str) -> set[str]:
    lowered = text.lower()
    latin_tokens = {
        token
        for token in re.findall(r"[a-z0-9][a-z0-9\-]{2,}", lowered)
        if len(token) >= 3
    }
    chinese_chunks = [chunk for chunk in re.findall(r"[\u4e00-\u9fa5]{2,}", text) if len(chunk) >= 2]
    chinese_tokens: set[str] = set(chinese_chunks)
    for chunk in chinese_chunks:
        if len(chunk) <= 2:
            continue
        for idx in range(len(chunk) - 1):
            chinese_tokens.add(chunk[idx : idx + 2])
    return latin_tokens | chinese_tokens


def tokenize_text(text: str) -> set[str]:
    return _tokenize(text)


def detect_scenario(claim_text: str) -> str:
    lowered = claim_text.lower()
    scored: dict[str, int] = {}
    for scenario, keywords in SCENARIO_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.isascii():
                if keyword in lowered:
                    score += 1
            else:
                if keyword in claim_text:
                    score += 1
        if score > 0:
            scored[scenario] = score
    if not scored:
        return "general"
    return max(scored, key=scored.get)


@lru_cache(maxsize=1)
def load_kb() -> list[KBEvidence]:
    if not KB_PATH.exists():
        return []
    raw = json.loads(KB_PATH.read_text(encoding="utf-8-sig"))
    return [
        KBEvidence(
            entry_id=item["id"],
            title=item["title"],
            source=item["source"],
            url=item["url"],
            published_at=item["published_at"],
            summary=item["summary"],
            tags=item.get("tags", []),
            domains=item.get("domains", ["general"]),
            stance_hint=item.get("stance_hint", "context"),
            credibility=float(item.get("credibility", 0.75)),
        )
        for item in raw
    ]


def domain_weight(url: str) -> float:
    host = urlparse(url).netloc.lower()
    if host.endswith(".gov.cn") or host.endswith(".gov"):
        return 0.96
    if "who.int" in host:
        return 0.94
    if "cdc.gov" in host:
        return 0.93
    if "reuters.com" in host:
        return 0.88
    return 0.72


def freshness_weight(published_at: str) -> float:
    try:
        published = datetime.strptime(published_at, "%Y-%m-%d").date()
    except ValueError:
        return 0.7

    days = (date.today() - published).days
    if days <= 30:
        return 1.0
    if days <= 180:
        return 0.9
    if days <= 365:
        return 0.8
    return 0.65


def _scenario_bonus(item_domains: list[str], scenario: str) -> float:
    if scenario == "general":
        return 0.0
    if scenario in item_domains:
        return 0.12
    return -0.03


def rank_evidence(claim_text: str, top_k: int = 3) -> list[tuple[KBEvidence, float]]:
    kb = load_kb()
    claim_tokens = _tokenize(claim_text)
    if not kb:
        return []

    scenario = detect_scenario(claim_text)

    ranked: list[tuple[KBEvidence, float]] = []
    for item in kb:
        text_tokens = _tokenize(f"{item.title} {item.summary} {' '.join(item.tags)} {' '.join(item.domains)}")
        overlap = len(claim_tokens & text_tokens)
        normalized_overlap = overlap / max(1, len(claim_tokens))
        claim_lower = claim_text.lower()
        tag_hit = 0.1 if any((tag in claim_text) or (tag.lower() in claim_lower) for tag in item.tags) else 0.0
        scenario_hit = _scenario_bonus(item.domains, scenario)
        score = (
            normalized_overlap * 0.5
            + item.credibility * 0.2
            + domain_weight(item.url) * 0.14
            + freshness_weight(item.published_at) * 0.08
            + tag_hit
            + scenario_hit
        )
        ranked.append((item, round(min(1.0, max(0.0, score)), 4)))

    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked[:top_k]


def infer_stance(claim_text: str, entry: KBEvidence, relevance: float) -> str:
    lowered = claim_text.lower()
    risk_terms = [
        "shocking",
        "inside source",
        "internal source",
        "100% true",
        "must share",
        "震惊",
        "内部消息",
        "必须转发",
        "包治百病",
    ]
    if any((term in lowered) or (term in claim_text) for term in risk_terms) and entry.stance_hint in {
        "refute",
        "context",
    }:
        return "refute"
    if relevance < 0.25:
        return "insufficient"
    if entry.stance_hint == "support":
        return "support"
    if entry.stance_hint == "refute":
        return "refute"
    return "insufficient"
