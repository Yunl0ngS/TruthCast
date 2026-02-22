import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib import error, request

from app.core.logger import get_logger
from app.schemas.detect import EvidenceItem, StrategyConfig
from app.services.json_utils import serialize_for_json

logger = get_logger("truthcast.evidence_summarization")


def summarize_evidence_for_claim(
    claim_text: str, evidences: list[EvidenceItem], strategy: StrategyConfig | None = None
) -> list[EvidenceItem]:
    if not evidences:
        return evidences
    
    target_min = strategy.summary_target_min if strategy else 1
    target_max = strategy.summary_target_max if strategy else min(len(evidences), 5)
    target_max = min(target_max, len(evidences))
    
    if target_max < 1:
        return evidences
    
    if not _summary_enabled():
        return evidences

    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("证据摘要：TRUTHCAST_LLM_API_KEY为空，跳过摘要层")
        return evidences

    rows = evidences[: _summary_input_limit()]
    logger.info(
        "证据摘要：开始处理 claim，输入证据=%s，目标范围=[%s, %s]",
        len(rows),
        target_min,
        target_max,
    )

    try:
        payload = _call_summary_llm(
            claim_text,
            rows,
            api_key=api_key,
            target_min=target_min,
            target_max=target_max,
        )
        summarized = _build_summary_evidences(payload, rows, max_items=target_max)
        logger.info(
            "证据摘要：处理完成，输出证据=%s（压缩比=%.2f）",
            len(summarized),
            len(summarized) / max(1, len(rows)),
        )
        return summarized
    except Exception as exc:  # noqa: BLE001
        logger.warning("证据摘要：LLM摘要失败，回退原始证据。error=%s", exc)
        return evidences


def _summary_enabled() -> bool:
    return os.getenv("TRUTHCAST_EVIDENCE_SUMMARY_ENABLED", "false").strip().lower() == "true"


def _summary_input_limit() -> int:
    raw = os.getenv("TRUTHCAST_EVIDENCE_SUMMARY_INPUT_LIMIT", "10").strip()
    try:
        value = int(raw)
    except ValueError:
        return 10
    return max(2, min(30, value))


def _call_summary_llm(
    claim_text: str, evidences: list[EvidenceItem], api_key: str, target_min: int, target_max: int
) -> dict[str, Any]:
    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1").strip()
    model = os.getenv(
        "TRUTHCAST_EVIDENCE_SUMMARY_LLM_MODEL",
        os.getenv("TRUTHCAST_LLM_MODEL", "gpt-4o-mini"),
    ).strip()
    endpoint = base_url.rstrip("/") + "/chat/completions"

    prompt = (
        "你是事实核验中的证据归纳引擎。请将同一主张对应的多条检索证据进行聚合，"
        "输出更少但信息完整的证据摘要。\n"
        "要求：\n"
        "1）只输出严格JSON。\n"
        f"2）输出 {target_min} 至 {target_max} 条摘要（根据证据质量自主决定数量）。\n"
        "3）每条摘要必须包含：summary_text、stance_hint(支持/反对/证据不足)、"
        "confidence(0~1)、source_indices。\n"
        "4）summary_text 用中文，简洁、可核查，不得编造。\n"
        "5）source_indices 必须引用输入证据下标（从0开始）。\n"
        "6）如果证据质量低或信息重复，可以输出更少的摘要。\n"
        "输出格式："
        '{"summaries":[{"summary_text":"","stance_hint":"支持","confidence":0.7,"source_indices":[0,2]}]}'
    )

    simplified = []
    for idx, item in enumerate(evidences):
        simplified.append(
            {
                "idx": idx,
                "title": item.title,
                "source": item.source,
                "url": item.url,
                "published_at": item.published_at,
                "summary": item.summary,
                "stance": item.stance,
                "score": item.source_weight,
            }
        )

    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是严谨的证据归纳助手，只返回JSON。"},
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n主张：\n{claim_text}\n\n"
                    f"证据列表：\n{json.dumps(simplified, ensure_ascii=False)}"
                ),
            },
        ],
    }

    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "45").strip() or 45)
    _record_summary_trace(
        stage="request",
        payload={
            "endpoint": endpoint,
            "timeout": timeout_val,
            "llm_payload": payload,
        },
    )

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError) as exc:
        _record_summary_trace(stage="error", payload={"error": str(exc)})
        raise RuntimeError(f"证据摘要LLM请求失败: {exc}") from exc

    body = json.loads(raw)
    content_raw = body["choices"][0]["message"]["content"]
    content = content_raw.strip()
    if content.startswith("```"):
        content = content.replace("```json", "").replace("```", "").strip()

    from app.services.json_utils import safe_json_loads
    
    parsed = safe_json_loads(content, "evidence_summarization")
    if parsed is None:
        _record_summary_trace(
            stage="parse_error",
            payload={
                "error": "JSON parse failed",
                "llm_content_raw": content_raw,
                "llm_content_cleaned": content,
            },
        )
        raise RuntimeError("证据摘要：JSON解析失败")
    
    _record_summary_trace(
        stage="response",
        payload={
            "llm_raw_http_response": body,
            "llm_content_raw": content_raw,
            "llm_content_cleaned": content,
            "parsed_json": parsed,
        },
    )
    return parsed


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


def _build_summary_evidences(
    payload: dict[str, Any], rows: list[EvidenceItem], max_items: int
) -> list[EvidenceItem]:
    summaries = payload.get("summaries", [])
    if not isinstance(summaries, list) or not summaries:
        logger.warning("证据摘要：payload 中无有效 summaries 字段，回退原始证据。payload=%s", payload)
        return rows

    result: list[EvidenceItem] = []
    for idx, item in enumerate(summaries[:max_items], start=1):
        if not isinstance(item, dict):
            logger.warning("证据摘要：summaries[%s] 不是 dict，跳过", idx - 1)
            continue
        summary_text = str(item.get("summary_text", "")).strip()
        stance_raw = item.get("stance_hint", "insufficient")
        stance = _normalize_stance(stance_raw)
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))

        indices = item.get("source_indices", [])
        if not isinstance(indices, list):
            indices = []
        source_rows = [
            rows[i] for i in indices if isinstance(i, int) and 0 <= i < len(rows)
        ]
        if not source_rows:
            logger.warning(
                "证据摘要：summaries[%s] 的 source_indices=%s 无效（rows 长度=%s），跳过",
                idx - 1, indices, len(rows)
            )
            continue

        base = source_rows[0]
        avg_weight = sum(x.source_weight for x in source_rows) / len(source_rows)
        merged_weight = round(max(0.0, min(1.0, avg_weight * max(0.3, confidence))), 4)
        merged_urls = [x.url for x in source_rows if x.url]
        merged_sources = [x.source for x in source_rows if x.source]
        raw_snippet = " | ".join(dict.fromkeys(merged_urls))[:1200]
        source_urls = list(dict.fromkeys(merged_urls))[:10]

        logger.info(
            "证据摘要：构建摘要证据 s%s, summary_text=%s, source_indices=%s, source_urls=%s",
            idx, summary_text[:50] + "..." if len(summary_text) > 50 else summary_text, indices, len(source_urls)
        )

        result.append(
            EvidenceItem(
                evidence_id=f"s{idx}",
                claim_id=base.claim_id,
                title=f"综合证据摘要 {idx}",
                source=" + ".join(dict.fromkeys(merged_sources))[:180] or "web-summary",
                url=base.url,
                published_at=base.published_at,
                summary=summary_text or base.summary,
                stance=stance,
                source_weight=merged_weight,
                source_type="web_summary",
                retrieved_at=base.retrieved_at,
                domain=base.domain,
                is_authoritative=all(bool(x.is_authoritative) for x in source_rows),
                raw_snippet=raw_snippet,
                source_urls=source_urls,
            )
        )

    if not result:
        logger.warning("证据摘要：所有摘要构建失败，回退原始证据")
        return rows

    return result


def _record_summary_trace(stage: str, payload: dict[str, Any]) -> None:
    if os.getenv("TRUTHCAST_DEBUG_EVIDENCE_SUMMARY", "true").strip().lower() != "true":
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "evidence_summary_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.error("写入 evidence summary trace 失败: %s", exc)
