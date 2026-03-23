import re
from dataclasses import dataclass

from app.services.url_extraction.extractors import ContentCandidate


@dataclass
class RankedCandidate:
    best: ContentCandidate | None
    confidence: str
    score: float
    fallback_needed: bool
    reasons: list[str]


def _title_bonus(content: str, title_hint: str) -> float:
    tokens = [token for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", title_hint or "") if len(token) >= 2]
    if not tokens:
        return 0.0
    head = content[:300]
    matches = sum(1 for token in tokens if token in head)
    return min(matches * 0.2, 1.0)


def _score_candidate(candidate: ContentCandidate, title_hint: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    if candidate.text_len >= 400:
        score += 3.0
        reasons.append("正文长度充足")
    elif candidate.text_len >= 150:
        score += 1.5
        reasons.append("正文长度可用")
    elif candidate.text_len >= 20:
        score += 0.5
        reasons.append("正文长度偏短但可判定")
    else:
        score -= 3.0
        reasons.append("正文过短")

    if candidate.paragraph_count >= 5:
        score += 2.0
        reasons.append("段落较完整")
    elif candidate.paragraph_count >= 2:
        score += 1.0
        reasons.append("具备基本段落结构")
    else:
        score -= 1.5
        reasons.append("段落过少")

    if candidate.link_density <= 0.2:
        score += 1.0
        reasons.append("链接密度较低")
    elif candidate.link_density >= 0.5:
        score -= 2.0
        reasons.append("链接密度过高")

    if candidate.noise_hits:
        score -= min(len(candidate.noise_hits), 3) * 0.8
        reasons.append("命中噪声词")

    if candidate.chinese_ratio >= 0.2:
        score += 0.5
        reasons.append("中文占比正常")

    title_bonus = _title_bonus(candidate.content, title_hint)
    if title_bonus:
        score += title_bonus
        reasons.append("标题匹配较好")

    return score, reasons


def rank_candidates(candidates: list[ContentCandidate], title_hint: str = "") -> RankedCandidate:
    if not candidates:
        return RankedCandidate(best=None, confidence="low", score=0.0, fallback_needed=True, reasons=["无可用候选"])

    scored: list[tuple[float, ContentCandidate, list[str]]] = []
    for candidate in candidates:
        score, reasons = _score_candidate(candidate, title_hint)
        candidate.raw_score = score
        scored.append((score, candidate, reasons))

    best_score, best_candidate, reasons = max(scored, key=lambda item: item[0])
    if best_score >= 4.0:
        confidence = "high"
    elif best_score >= 1.5:
        confidence = "medium"
    else:
        confidence = "low"
    return RankedCandidate(
        best=best_candidate,
        confidence=confidence,
        score=best_score,
        fallback_needed=confidence == "low",
        reasons=reasons,
    )
