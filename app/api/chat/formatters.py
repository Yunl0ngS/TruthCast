from typing import Any


_RISK_LABEL_ZH = {
    "credible": "可信",
    "suspicious": "可疑",
    "high_risk": "高风险",
    "needs_context": "需要补充语境",
    "likely_misinformation": "疑似不实信息",
}

_RISK_LEVEL_ZH = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "极高",
}

_SCENARIO_ZH = {
    "general": "通用",
    "health": "医疗健康",
    "governance": "政务治理",
    "security": "公共安全",
    "media": "媒体传播",
    "technology": "科技产业",
    "education": "教育校园",
}

_DOMAIN_ZH = {
    "general": "通用",
    "health": "医疗健康",
    "governance": "政务治理",
    "security": "公共安全",
    "media": "媒体传播",
    "technology": "科技产业",
    "education": "教育校园",
}

_STANCE_ZH = {
    "support": "支持",
    "refute": "反对",
    "oppose": "反对",
    "insufficient": "证据不足",
    "insufficient_evidence": "证据不足",
}

_CLAIM_SEPARATOR = "=" * 56
_EVIDENCE_SEPARATOR = "-" * 44


def _zh_risk_label(label: Any) -> str:
    raw = str(label or "").strip()
    if not raw:
        return "未知"
    return _RISK_LABEL_ZH.get(raw, raw)


def _zh_risk_level(level: Any) -> str:
    raw = str(level or "").strip()
    if not raw:
        return "未知"
    return _RISK_LEVEL_ZH.get(raw, raw)


def _zh_stance(stance: Any) -> str:
    raw = str(stance or "").strip()
    if not raw:
        return "证据不足"
    return _STANCE_ZH.get(raw, raw)


def _zh_scenario(scenario: Any) -> str:
    raw = str(scenario or "").strip()
    if not raw:
        return "未知"
    return _SCENARIO_ZH.get(raw, raw)


def _zh_domain(domain: Any) -> str:
    raw = str(domain or "").strip()
    if not raw:
        return ""
    return _DOMAIN_ZH.get(raw, raw)


def _truncate_text(value: Any, limit: int = 60) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."
