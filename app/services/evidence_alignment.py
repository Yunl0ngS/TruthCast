import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.core.logger import get_logger
from app.schemas.detect import EvidenceItem
from app.services.json_utils import serialize_for_json

logger = get_logger("truthcast.evidence_alignment")

DEBUG_ALIGNMENT = os.getenv("TRUTHCAST_DEBUG_ALIGNMENT", "true").strip().lower() == "true"

_STANCE_ZH_TO_EN = {
    "支持": "support",
    "反对": "refute",
    "反驳": "refute",
    "证据不足": "insufficient",
    "不足": "insufficient",
    "不确定": "insufficient",
    "中立": "insufficient",
}


def _normalize_stance(stance_raw: str) -> str:
    """将中文/英文 stance 统一转换为英文标准值"""
    stance = str(stance_raw).strip().lower()
    if stance in {"support", "refute", "insufficient"}:
        return stance
    stance_zh = str(stance_raw).strip()
    if stance_zh in _STANCE_ZH_TO_EN:
        return _STANCE_ZH_TO_EN[stance_zh]
    return "insufficient"


def _record_alignment_trace(stage: str, payload: dict[str, Any]) -> None:
    """记录对齐 trace 日志"""
    if not DEBUG_ALIGNMENT:
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "alignment_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 alignment trace 失败: %s", exc)


@dataclass
class AlignmentResult:
    stance: str
    confidence: float
    rationale: str


def align_claim_with_evidence(claim_text: str, evidence: EvidenceItem) -> AlignmentResult:
    _record_alignment_trace(
        "input",
        {
            "claim_text": claim_text[:200],
            "evidence_id": evidence.evidence_id,
            "evidence_title": evidence.title[:100],
            "evidence_source_type": evidence.source_type,
            "evidence_stance": evidence.stance,
            "evidence_source_weight": evidence.source_weight,
            "llm_enabled": _alignment_llm_enabled(),
        },
    )

    if _alignment_llm_enabled():
        logger.info("证据对齐：LLM模式已启用，开始尝试LLM对齐")
        llm_result = _align_with_llm(claim_text, evidence)
        if llm_result is not None:
            logger.info(
                "证据对齐：LLM对齐成功，stance=%s, confidence=%.2f",
                llm_result.stance,
                llm_result.confidence,
            )
            _record_alignment_trace(
                "llm_output",
                {
                    "path": "llm",
                    "stance": llm_result.stance,
                    "confidence": llm_result.confidence,
                    "rationale": llm_result.rationale,
                },
            )
            return llm_result
        logger.warning("证据对齐：LLM对齐失败，已回退规则对齐")
    else:
        logger.info("证据对齐：LLLM模式未启用，使用规则对齐")

    result = _align_rule_based(claim_text, evidence)
    _record_alignment_trace(
        "rule_output",
        {
            "path": "rule",
            "stance": result.stance,
            "confidence": result.confidence,
            "rationale": result.rationale,
        },
    )
    return result


def _alignment_llm_enabled() -> bool:
    direct = os.getenv("TRUTHCAST_ALIGNMENT_LLM_ENABLED", "").strip().lower()
    if direct in {"true", "false"}:
        return direct == "true"
    return os.getenv("TRUTHCAST_LLM_ENABLED", "false").strip().lower() == "true"


def _align_with_llm(claim_text: str, evidence: EvidenceItem) -> AlignmentResult | None:
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("证据对齐：TRUTHCAST_LLM_API_KEY为空，无法调用LLM")
        return None

    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("TRUTHCAST_ALIGNMENT_LLM_MODEL", os.getenv("TRUTHCAST_LLM_MODEL", "gpt-4o-mini"))
    endpoint = base_url.rstrip("/") + "/chat/completions"

    prompt = (
        "你是证据对齐引擎。请根据 主张 与 证据 判断关系，并只返回严格 JSON。\n"
        "输出结构：{\"stance\":\"支持|反对|证据不足\",\"confidence\":0~1,\"rationale\":\"中文解释\"}\n"
        "要求：\n"
        "1）只输出 JSON，不要额外文本。\n"
        "2）当证据不足时必须返回 证据不足。\n"
        "3）rationale 用简洁中文说明主要依据。"
    )

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是严谨的事实核验助手。"},
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n"
                    f"主张:\n{claim_text}\n\n"
                    f"证据标题:\n{evidence.title}\n\n"
                    f"证据总结:\n{evidence.summary}\n\n"
                    f"证据源:{evidence.source}, 权重:{evidence.source_weight}"
                ),
            },
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "60"))

    _record_alignment_trace(
        "llm_request",
        {
            "endpoint": endpoint,
            "timeout": timeout_val,
            "model": model,
            "payload": payload,
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        logger.warning("证据对齐：LLM请求失败或超时，将回退规则对齐。错误=%s", exc)
        _record_alignment_trace("llm_error", {"error_type": "URLError/Timeout", "error": str(exc)})
        return None
    except Exception as exc:
        logger.error("证据对齐：LLM请求发生未知错误，错误=%s", exc)
        _record_alignment_trace("llm_error", {"error_type": "Unknown", "error": str(exc)})
        return None

    try:
        body = json.loads(raw)
        content = body["choices"][0]["message"]["content"].strip()
        content_raw = content
        if content.startswith("```"):
            content = content.replace("```json", "").replace("```", "").strip()
        
        from app.services.json_utils import safe_json_loads
        
        result = safe_json_loads(content, "evidence_alignment")
        if result is None:
            logger.error("证据对齐：JSON解析失败")
            _record_alignment_trace("llm_parse_error", {"error": "JSON parse failed", "content_cleaned": content})
            return None
        
        _record_alignment_trace(
            "llm_response",
            {
                "llm_raw_response": body,
                "content_raw": content_raw,
                "content_cleaned": content,
                "parsed_json": result,
            },
        )
        
        normalized = _normalize_llm_result(result)
        if normalized is None:
            _record_alignment_trace("llm_normalize_failed", {"parsed_json": result})
        return normalized
    except Exception as exc:
        logger.error("证据对齐：LLM响应解析失败，错误=%s", exc)
        _record_alignment_trace("llm_parse_error", {"error": str(exc), "raw_response": raw[:500]})
        return None


def _normalize_llm_result(payload: dict[str, Any]) -> AlignmentResult | None:
    stance_raw = payload.get("stance", "")
    stance = _normalize_stance(stance_raw)
    if stance not in {"support", "refute", "insufficient"}:
        return None

    try:
        confidence = float(payload.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    rationale = str(payload.get("rationale", "")).strip() or "模型未提供理由，已回退默认说明。"
    return AlignmentResult(stance=stance, confidence=round(confidence, 2), rationale=rationale)


def _align_rule_based(claim_text: str, evidence: EvidenceItem) -> AlignmentResult:
    evidence_text = f"{evidence.title} {evidence.summary}".lower()

    claim_tokens = _tokens(claim_text)
    evidence_tokens = _tokens(evidence_text)
    overlap = claim_tokens & evidence_tokens
    overlap_ratio = len(overlap) / max(1, len(claim_tokens))

    risk_terms = {
        "shocking",
        "internal",
        "inside",
        "100",
        "must",
        "share",
        "rumor",
        "miracle",
        "震惊",
        "内部消息",
        "必须转发",
        "旧闻翻炒",
    }
    official_terms = {
        "official",
        "statement",
        "bulletin",
        "guidance",
        "notice",
        "通报",
        "公告",
        "官方",
        "权威",
    }
    refute_terms = {
        "myth",
        "misconception",
        "fact-check",
        "misleading",
        "rumor-control",
        "辟谣",
        "谣言",
        "断章取义",
    }

    has_risk = len(claim_tokens & risk_terms) > 0
    has_official = len(evidence_tokens & official_terms) > 0
    has_refute = len(evidence_tokens & refute_terms) > 0

    score = overlap_ratio * 0.55 + evidence.source_weight * 0.45
    score = round(min(1.0, max(0.0, score)), 2)

    matched_rule = ""
    result = None

    if has_risk and has_refute:
        matched_rule = "risk_refute"
        result = AlignmentResult(
            stance="refute",
            confidence=max(0.55, score),
            rationale="主张含高风险传播话术，且证据来自辟谣或误导说明来源，倾向反驳。",
        )

    if result is None and has_official and overlap_ratio >= 0.15:
        matched_rule = "official_support"
        result = AlignmentResult(
            stance="support",
            confidence=max(0.5, score),
            rationale="证据来自官方通报或权威说明，且与主张关键词存在匹配，倾向支持。",
        )

    if result is None and overlap_ratio < 0.08:
        matched_rule = "low_overlap"
        result = AlignmentResult(
            stance="insufficient",
            confidence=min(0.5, score),
            rationale="主张与证据关键词重合较低，当前证据不足以直接判断。",
        )

    if result is None and evidence.stance in {"support", "refute"}:
        matched_rule = "inherit_stance"
        result = AlignmentResult(
            stance=evidence.stance,
            confidence=max(0.45, score),
            rationale="检索来源与关键词匹配可用，沿用检索阶段立场并给出中等置信度。",
        )

    if result is None:
        matched_rule = "default"
        result = AlignmentResult(
            stance="insufficient",
            confidence=min(0.55, score),
            rationale="证据与主张存在部分相关，但不足以构成明确支持或反驳。",
        )

    _record_alignment_trace(
        "rule_calculation",
        {
            "claim_tokens_count": len(claim_tokens),
            "evidence_tokens_count": len(evidence_tokens),
            "overlap_tokens": list(overlap)[:20],
            "overlap_ratio": overlap_ratio,
            "source_weight": evidence.source_weight,
            "base_score": score,
            "has_risk": has_risk,
            "has_official": has_official,
            "has_refute": has_refute,
            "matched_rule": matched_rule,
            "result_stance": result.stance,
            "result_confidence": result.confidence,
        },
    )

    return result


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9\u4e00-\u9fa5][a-z0-9\u4e00-\u9fa5\-]{1,}", text.lower())
        if len(token) >= 2
    }
