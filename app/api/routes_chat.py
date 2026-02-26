import asyncio
import json
import hashlib
import os
import time
from typing import Any, Iterator, cast

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.concurrency import llm_slot
from app.core.logger import get_logger
from app.core.guardrails import (
    build_guardrails_warning_message,
    validate_tool_call,
)
from app.orchestrator import orchestrator
from app.schemas.chat import (
    ChatAction,
    ChatMessage,
    ChatMessageCreateRequest,
    ChatReference,
    ChatRequest,
    ChatResponse,
    ChatSession,
    ChatSessionCreateRequest,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
    ChatStreamEvent,
)
from app.schemas.detect import (
    ClaimItem,
    ClarificationStyle,
    ContentGenerateResponse,
    ContentGenerateRequest,
    EvidenceItem,
    Platform,
    ReportResponse,
    SimulateResponse,
)
from app.services import chat_store
from app.services.chat_orchestrator import (
    ToolAnalyzeArgs,
    ToolAlignOnlyArgs,
    ToolClaimsOnlyArgs,
    ToolCompareArgs,
    ToolContentGenerateArgs,
    ToolDeepDiveArgs,
    ToolEvidenceOnlyArgs,
    ToolListArgs,
    ToolLoadHistoryArgs,
    ToolMoreEvidenceArgs,
    ToolReportOnlyArgs,
    ToolRewriteArgs,
    ToolSimulateArgs,
    ToolWhyArgs,
    build_intent_clarify_message,
    build_help_message,
    build_why_usage_message,
    parse_tool,
    run_compare,
    run_deep_dive,
    run_list,
    run_load_history,
    run_more_evidence,
    run_rewrite,
    run_why,
)
from app.services.content_generation import generate_full_content
from app.services.history_store import get_history, save_report, update_content, update_simulation
from app.services.opinion_simulation import simulate_opinion_stream
from app.services.pipeline import align_evidences
from app.services.pipeline_state_store import get_phase_payload, load_task, upsert_phase_snapshot
from app.services.risk_snapshot import detect_risk_snapshot

router = APIRouter(prefix="/chat", tags=["chat"])
logger = get_logger(__name__)


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


def _session_tool_max_calls() -> int:
    raw = (os.getenv("TRUTHCAST_SESSION_TOOL_MAX_CALLS") or "50").strip()
    try:
        return max(1, min(500, int(raw)))
    except ValueError:
        return 50


def _session_llm_max_calls() -> int:
    raw = (os.getenv("TRUTHCAST_SESSION_LLM_MAX_CALLS") or "20").strip()
    try:
        return max(1, min(200, int(raw)))
    except ValueError:
        return 20


def _session_cache_ttl_sec() -> int:
    raw = (os.getenv("TRUTHCAST_SESSION_CACHE_TTL_SEC") or "300").strip()
    try:
        return max(30, min(3600, int(raw)))
    except ValueError:
        return 300


def _session_hash_bucket_limit() -> int:
    raw = (os.getenv("TRUTHCAST_SESSION_HASH_BUCKET_LIMIT") or "8").strip()
    try:
        return max(1, min(30, int(raw)))
    except ValueError:
        return 8

def _emit_sse_token(session_id: str, content: str) -> str:
    """生成 SSE token 事件字符串。"""
    event = ChatStreamEvent(type="token", data={"content": content, "session_id": session_id})
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_stage(session_id: str, stage: str, status: str) -> str:
    """生成 SSE stage 事件字符串。"""
    event = ChatStreamEvent(type="stage", data={"session_id": session_id, "stage": stage, "status": status})
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_message(session_id: str, message: ChatMessage) -> str:
    """生成 SSE message 事件字符串。"""
    event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": message.model_dump()})
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_done(session_id: str) -> str:
    """生成 SSE done 事件字符串。"""
    event = ChatStreamEvent(type="done", data={"session_id": session_id})
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_error(session_id: str, error_message: str) -> str:
    """生成 SSE error 事件字符串。"""
    event = ChatStreamEvent(type="error", data={"session_id": session_id, "message": error_message})
    return f"data: {event.model_dump_json()}\n\n"


def _safe_append_message(session_id: str, msg: ChatMessage) -> None:
    """安全写入消息到会话库（失败不阻断）。"""
    try:
        chat_store.append_message(
            session_id,
            role=msg.role,
            content=msg.content,
            actions=[a.model_dump() for a in (msg.actions or [])],
            references=[r.model_dump() for r in (msg.references or [])],
            meta=msg.meta,
        )
    except Exception:
        pass

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


def _new_session_id() -> str:
    return f"chat_{int(time.time() * 1000)}"


def _ensure_session(session_id: str | None) -> str:
    """确保 session 在会话库中存在；返回最终 session_id。"""

    if session_id:
        existing = chat_store.get_session(session_id)
        if existing is not None:
            return session_id

    created = chat_store.create_session(title=None, meta=None)
    return str(created["session_id"])


def _is_analyze_intent(text: str) -> bool:
    t = text.strip()
    return t.startswith("/analyze ")


def _extract_analyze_text(text: str) -> str:
    t = text.strip()
    if t.startswith("/analyze "):
        return t[len("/analyze ") :].strip()
    return t


def _hash_input_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def _stable_hash_payload(value: Any) -> str:
    encoded = jsonable_encoder(value)
    raw = json.dumps(encoded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _is_cache_hit(entry: Any, expected_key: str) -> bool:
    if not isinstance(entry, dict):
        return False
    key = str(entry.get("key") or "")
    ts = entry.get("ts")
    if key != expected_key:
        return False
    if not isinstance(ts, (int, float)):
        return False
    return (time.time() - float(ts)) <= _session_cache_ttl_sec()


def _save_session_cache_entry(session_id: str, cache_field: str, key: str) -> None:
    chat_store.update_session_meta_fields(
        session_id,
        {
            cache_field: {
                "key": key,
                "ts": int(time.time()),
            }
        },
    )


def _build_missing_dependency_message(*, tool_name: str, detail: str, suggestion: str) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=f"{tool_name} 无法执行：{detail}\n\n建议：{suggestion}",
        actions=[ChatAction(type="command", label="查看帮助", command="/help")],
        references=[],
    )


def _handle_single_skill_tool(
    *, session_id: str, tool: str, args_dict: dict[str, Any], session_meta: dict[str, Any]
) -> Iterator[str]:
    def _raw_hash_buckets() -> dict[str, Any]:
        data = session_meta.get("phase_payload_buckets")
        return data if isinstance(data, dict) else {}

    def _normalize_hash_buckets() -> dict[str, dict[str, Any]]:
        raw = _raw_hash_buckets()
        out: dict[str, dict[str, Any]] = {}
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, dict):
                out[key] = value
        return out

    def _persist_hash_buckets(buckets: dict[str, dict[str, Any]]) -> None:
        limit = _session_hash_bucket_limit()
        items = sorted(
            buckets.items(),
            key=lambda it: float((it[1] or {}).get("updated_at") or 0.0),
            reverse=True,
        )
        trimmed = dict(items[:limit])
        chat_store.update_session_meta_fields(session_id, {"phase_payload_buckets": trimmed})
        session_meta["phase_payload_buckets"] = trimmed

    def _store_hash_phase(*, input_hash: str, phase: str, payload: dict[str, Any], input_text: str) -> None:
        if not input_hash:
            return
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        bucket[phase] = payload
        bucket["input_text"] = input_text
        bucket["updated_at"] = int(time.time())
        buckets[input_hash] = bucket
        _persist_hash_buckets(buckets)

    def _clear_hash_phases(input_hash: str, phases_to_clear: list[str]) -> None:
        if not input_hash:
            return
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        changed = False
        for phase_name in phases_to_clear:
            if phase_name in bucket:
                bucket.pop(phase_name, None)
                changed = True
        if changed:
            bucket["updated_at"] = int(time.time())
            buckets[input_hash] = bucket
            _persist_hash_buckets(buckets)

    def _get_hash_phase(input_hash: str, phase: str) -> dict[str, Any]:
        if not input_hash:
            return {}
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        payload = bucket.get(phase)
        return payload if isinstance(payload, dict) else {}

    def _get_hash_input_text(input_hash: str) -> str:
        if not input_hash:
            return ""
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        return str(bucket.get("input_text") or "")

    def _current_phases() -> dict[str, str]:
        task = load_task(session_id) or {}
        raw_phases = task.get("phases")
        phases: dict[str, Any] = raw_phases if isinstance(raw_phases, dict) else {}
        base = {
            "detect": "idle",
            "claims": "idle",
            "evidence": "idle",
            "align": "idle",
            "report": "idle",
            "simulation": "idle",
            "content": "idle",
        }
        base.update({str(k): str(v) for k, v in phases.items()})
        return base

    def _emit_and_store(msg: ChatMessage) -> Iterator[str]:
        _safe_append_message(session_id, msg)
        yield _emit_sse_message(session_id, msg)
        yield _emit_sse_done(session_id)

    def _check_and_bump_tool_budget() -> ChatMessage | None:
        current = int(session_meta.get("tool_call_count") or 0)
        limit = _session_tool_max_calls()
        if current >= limit:
            return ChatMessage(
                role="assistant",
                content=(
                    f"当前会话工具调用已达上限（{limit} 次）。\n\n"
                    "建议：新建会话后继续，或使用 /session switch 切换到其他会话。"
                ),
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
        chat_store.update_session_meta_fields(session_id, {"tool_call_count": current + 1})
        session_meta["tool_call_count"] = current + 1
        return None

    def _check_and_bump_llm_budget() -> ChatMessage | None:
        current = int(session_meta.get("llm_call_count") or 0)
        limit = _session_llm_max_calls()
        if current >= limit:
            return ChatMessage(
                role="assistant",
                content=(
                    f"当前会话 LLM 调用已达上限（{limit} 次）。\n\n"
                    "建议：新建会话后继续，或减少重复调用高成本工具。"
                ),
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
        chat_store.update_session_meta_fields(session_id, {"llm_call_count": current + 1})
        session_meta["llm_call_count"] = current + 1
        return None

    budget_msg = _check_and_bump_tool_budget()
    if budget_msg is not None:
        yield from _emit_and_store(budget_msg)
        return

    if tool == "claims_only":
        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return
        try:
            args = ToolClaimsOnlyArgs.model_validate(args_dict)
        except ValidationError:
            usage = ChatMessage(
                role="assistant",
                content="用法：/claims_only <待分析文本>",
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
            yield from _emit_and_store(usage)
            return
        input_text = args.text.strip()
        if not input_text:
            empty_msg = ChatMessage(
                role="assistant",
                content="用法：/claims_only <待分析文本>（文本不能为空）",
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
            yield from _emit_and_store(empty_msg)
            return

        # SSE stage: running
        yield _emit_sse_stage(session_id, "claims_only", "running")
        yield _emit_sse_token(session_id, "正在分析文本并提取核心主张...\n")
        input_hash = _hash_input_text(input_text)
        _clear_hash_phases(
            input_hash,
            ["evidence_search", "evidence", "evidence_align", "align", "report", "simulation", "content"],
        )
        with llm_slot():
            claims = orchestrator.run_claims(input_text)
        # 构建可读的 claims 列表展示
        token_lines = []
        if not claims:
            token_lines.append("未能提取到有效主张（文本可能不包含可核查的事实陈述）\n")
        else:
            token_lines.append(f"已提取 {len(claims)} 条核心主张：\n\n")
            for idx, c in enumerate(claims, start=1):
                claim_id = getattr(c, "claim_id", f"C{idx}")
                claim_text = getattr(c, "text", "")
                claim_entity = getattr(c, "entity", "")
                claim_time = getattr(c, "time", "")
                claim_location = getattr(c, "location", "")
                
                token_lines.append(f"{_CLAIM_SEPARATOR}\n")
                token_lines.append(f"[{claim_id}] {claim_text}\n")
                if claim_entity:
                    token_lines.append(f"  - 涉及实体: {claim_entity}\n")
                if claim_time:
                    token_lines.append(f"  - 时间: {claim_time}\n")
                if claim_location:
                    token_lines.append(f"  - 地点: {claim_location}\n")
                token_lines.append("\n")

        # 逐条输出 token 事件
        for line in token_lines:
            yield _emit_sse_token(session_id, line)

        # 持久化中间态
        phases = _current_phases()
        phases["claims"] = "done"
        phases["evidence"] = "idle"
        phases["align"] = "idle"
        phases["report"] = "idle"
        phases["simulation"] = "idle"
        phases["content"] = "idle"
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="claims",
            status="done",
            payload={"claims": [c.model_dump() for c in claims]},
            meta={"source": "chat", "input_text_hash": input_hash},
        )
        _store_hash_phase(
            input_hash=input_hash,
            phase="claims",
            payload={"claims": [c.model_dump() for c in claims]},
            input_text=input_text,
        )
        chat_store.update_session_meta_fields(
            session_id,
            {
                "last_phase": "claims",
                "last_task_id": session_id,
                "input_text_hash": input_hash,
                "bound_record_id": str(session_meta.get("bound_record_id") or ""),
            },
        )
        session_meta["input_text_hash"] = input_hash

        # SSE stage: done
        yield _emit_sse_stage(session_id, "claims_only", "done")

        # 最终 message 事件
        summary_content = f"主张抽取完成：已提取 {len(claims)} 条主张并保存到 session 中间态。"
        if not claims:
            summary_content = "主张抽取完成：未提取到有效主张（可能文本不包含明确事实陈述）。"
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[ChatAction(type="command", label="继续证据检索", command=f"/evidence_only {input_text}")] if claims else [],
            references=[],
            meta={"phase": "claims", "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return

    if tool == "evidence_only":
        try:
            args = ToolEvidenceOnlyArgs.model_validate(args_dict)
        except ValidationError:
            usage = ChatMessage(
                role="assistant",
                content="用法：/evidence_only <与 claims_only 相同的原文>（可选：在会话中先绑定 record_id）",
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
            yield from _emit_and_store(usage)
            return
        input_text = args.text.strip()
        if not input_text:
            empty_msg = ChatMessage(
                role="assistant",
                content="用法：/evidence_only <待检索原文>（文本不能为空）",
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
            yield from _emit_and_store(empty_msg)
            return
        input_hash = _hash_input_text(input_text)
        existing_hash = str(session_meta.get("input_text_hash") or "")
        claims_payload = _get_hash_phase(input_hash, "claims")
        if not claims_payload and existing_hash == input_hash:
            claims_payload = get_phase_payload(session_id, "claims") or {}
        claims_data = claims_payload.get("claims") if isinstance(claims_payload, dict) else None
        claims: list[ClaimItem] = []
        source_desc = "session"
        if isinstance(claims_data, list):
            claims = [ClaimItem.model_validate(item) for item in claims_data]
        if not claims and input_text:
            llm_budget_msg = _check_and_bump_llm_budget()
            if llm_budget_msg is not None:
                yield from _emit_and_store(llm_budget_msg)
                return
            yield _emit_sse_token(session_id, "检测到缺少主张中间态，已自动执行主张抽取前置阶段...\n")
            with llm_slot():
                claims = orchestrator.run_claims(input_text)
            yield _emit_sse_token(session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n")
            for idx, claim in enumerate(claims, start=1):
                claim_text = getattr(claim, "text", "")
                claim_id = getattr(claim, "claim_id", f"C{idx}")
                yield _emit_sse_token(session_id, f"{idx}. [{claim_id}] {claim_text}\n")
            yield _emit_sse_token(session_id, "\n")
            phases = _current_phases()
            phases["claims"] = "done"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=input_text,
                phases=phases,
                phase="claims",
                status="done",
                payload={"claims": [c.model_dump() for c in claims]},
                meta={"source": "chat", "input_text_hash": input_hash, "auto_planned": True},
            )
            _store_hash_phase(
                input_hash=input_hash,
                phase="claims",
                payload={"claims": [c.model_dump() for c in claims]},
                input_text=input_text,
            )
            chat_store.update_session_meta_fields(
                session_id,
                {
                    "last_phase": "claims",
                    "last_task_id": session_id,
                    "input_text_hash": input_hash,
                },
            )
            session_meta["input_text_hash"] = input_hash
        # 只有 session claims 为空时才从 record_id 回退
        if not claims and args.record_id:
            record = get_history(args.record_id)
            if record:
                reports = ((record.get("report") or {}).get("claim_reports") or [])
                claims = [ClaimItem.model_validate((row or {}).get("claim")) for row in reports if (row or {}).get("claim")]
                source_desc = "record_id"
        if not claims:
            dep = _build_missing_dependency_message(
                tool_name="evidence_only",
                detail="缺少可用 claims 中间态。",
                suggestion="先执行 /claims_only <文本>，或提供含 claims 的 record_id。",
            )
            yield from _emit_and_store(dep)
            return
        _clear_hash_phases(input_hash, ["evidence_align", "align", "report", "simulation", "content"])

        # SSE stage: running
        yield _emit_sse_stage(session_id, "evidence_only", "running")

        # 执行证据检索
        evidences = orchestrator.run_evidence(text=input_text, claims=claims)
        # SSE token 流式输出：原始检索证据块（按主张分组）
        token_lines = []
        token_lines.append("【原始检索证据】\n\n")
        if not evidences:
            token_lines.append("未检索到有效证据。\n")
        else:
            # 按主张分组展示证据
            claim_evidence_map: dict[str, list[EvidenceItem]] = {}
            for ev in evidences:
                cid = getattr(ev, "claim_id", "未知")
                if cid not in claim_evidence_map:
                    claim_evidence_map[cid] = []
                claim_evidence_map[cid].append(ev)

            for claim in claims:
                cid = getattr(claim, "claim_id", "未知")
                claim_text = getattr(claim, "text", "（无主张文本）")
                evs = claim_evidence_map.get(cid, [])

                token_lines.append(f"{_CLAIM_SEPARATOR}\n")
                token_lines.append(f"[{cid}] {claim_text}\n\n")

                if not evs:
                    token_lines.append("  （无检索证据）\n\n")
                else:
                    for idx, ev in enumerate(evs, start=1):
                        token_lines.append(f"{_EVIDENCE_SEPARATOR}\n")
                        title = getattr(ev, "title", "")
                        url = getattr(ev, "url", "")
                        summary = getattr(ev, "summary", "")
                        token_lines.append(f"[证据 {idx}]\n")
                        if title:
                            token_lines.append(f"[标题] {title}\n")
                        if url:
                            token_lines.append(f"[来源链接] {url}\n")
                        if summary:
                            token_lines.append(f"[摘要] {summary}\n")
                        token_lines.append("\n")

        # 逐条输出 token 事件
        for line in token_lines:
            yield _emit_sse_token(session_id, line)

        # 持久化中间态
        phases = _current_phases()
        phases["evidence_search"] = "done"
        phases["align"] = "idle"
        phases["report"] = "idle"
        phases["simulation"] = "idle"
        phases["content"] = "idle"
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="evidence_search",
            status="done",
            payload={
                "claims": [c.model_dump() for c in claims],
                "evidences": [e.model_dump() for e in evidences],
            },
            meta={"source": "chat", "input_text_hash": input_hash},
        )
        chat_store.update_session_meta_fields(
            session_id,
            {
                "last_phase": "evidence_search",
                "last_task_id": session_id,
                "input_text_hash": input_hash,
                "bound_record_id": str(session_meta.get("bound_record_id") or ""),
            },
        )
        session_meta["input_text_hash"] = input_hash
        _store_hash_phase(
            input_hash=input_hash,
            phase="evidence_search",
            payload={
                "claims": [c.model_dump() for c in claims],
                "evidences": [e.model_dump() for e in evidences],
            },
            input_text=input_text,
        )
        _store_hash_phase(
            input_hash=input_hash,
            phase="evidence",
            payload={
                "claims": [c.model_dump() for c in claims],
                "evidences": [e.model_dump() for e in evidences],
            },
            input_text=input_text,
        )

        # SSE stage: done
        yield _emit_sse_stage(session_id, "evidence_only", "done")

        # 最终 message 事件
        summary_content = f"证据检索完成：复用 {source_desc} 的 claims，检索到 {len(evidences)} 条证据并保存到 session 中间态。"
        if not evidences:
            summary_content = "证据检索完成：未检索到有效证据。"
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[ChatAction(type="command", label="继续证据对齐", command="/align_only")] if evidences else [],
            references=[],
            meta={"phase": "evidence", "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return

    if tool == "align_only":
        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return
        args = ToolAlignOnlyArgs.model_validate(args_dict)
        preferred_text = str(args.text or "").strip()
        active_hash = str(session_meta.get("input_text_hash") or "")
        if preferred_text:
            active_hash = _hash_input_text(preferred_text)
        # 先尝试读 evidence_search，向后兼容老 evidence
        evidence_payload = (
            _get_hash_phase(active_hash, "evidence_search")
            or _get_hash_phase(active_hash, "evidence")
            or get_phase_payload(session_id, "evidence_search")
            or get_phase_payload(session_id, "evidence")
            or {}
        )
        claims = [ClaimItem.model_validate(item) for item in (evidence_payload.get("claims") or []) if isinstance(item, dict)]
        evidences = [EvidenceItem.model_validate(item) for item in (evidence_payload.get("evidences") or []) if isinstance(item, dict)]

        if (not claims or not evidences) and args.record_id:
            record = get_history(args.record_id)

            if record:
                claim_reports = ((record.get("report") or {}).get("claim_reports") or [])
                claims = [ClaimItem.model_validate((row or {}).get("claim")) for row in claim_reports if (row or {}).get("claim")]
                evidences = [
                    EvidenceItem.model_validate(item)
                    for row in claim_reports
                    for item in ((row or {}).get("evidences") or [])
                    if isinstance(item, dict)
                ]
        if (not claims or not evidences) and preferred_text:
            yield _emit_sse_token(session_id, "检测到缺少证据中间态，正在自动补齐前置阶段（主张->证据）...\n")
            claims_payload = _get_hash_phase(active_hash, "claims") or get_phase_payload(session_id, "claims") or {}
            claims_data = claims_payload.get("claims") if isinstance(claims_payload, dict) else None
            claims = [ClaimItem.model_validate(item) for item in (claims_data or []) if isinstance(item, dict)]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(preferred_text)
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=preferred_text,
                )
            if claims:
                evidences = orchestrator.run_evidence(text=preferred_text, claims=claims)
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in evidences]},
                    input_text=preferred_text,
                )
        if not claims or not evidences:
            dep = _build_missing_dependency_message(
                tool_name="align_only",
                detail="缺少 claims/evidences 中间态。",
                suggestion="先执行 /evidence_only，或提供包含 report 的 record_id。",
            )
            yield from _emit_and_store(dep)
            return
        _clear_hash_phases(active_hash, ["report", "simulation", "content"])

        # SSE stage: running
        yield _emit_sse_stage(session_id, "align_only", "running")
        with llm_slot():
            aligned = align_evidences(claims=claims, evidences=evidences)
        # SSE token 流式输出：聚合后证据块（按主张分组）
        token_lines = []
        token_lines.append("【聚合后证据】\n\n")
        if not aligned:
            token_lines.append("未生成对齐证据。\n")
        else:
            # 按主张分组展示聚合后证据
            claim_evidence_map: dict[str, list[EvidenceItem]] = {}
            for ev in aligned:
                cid = getattr(ev, "claim_id", "未知")
                if cid not in claim_evidence_map:
                    claim_evidence_map[cid] = []
                claim_evidence_map[cid].append(ev)

            for claim in claims:
                cid = getattr(claim, "claim_id", "未知")
                claim_text = getattr(claim, "text", "（无主张文本）")
                evs = claim_evidence_map.get(cid, [])

                token_lines.append(f"{_CLAIM_SEPARATOR}\n")
                token_lines.append(f"[{cid}] {claim_text}\n\n")

                if not evs:
                    token_lines.append("  （无聚合证据）\n\n")
                else:
                    for idx, ev in enumerate(evs, start=1):
                        token_lines.append(f"{_EVIDENCE_SEPARATOR}\n")
                        
                        # 聚合证据标题（必需字段）
                        summary_text = getattr(ev, "summary", "") or getattr(ev, "title", "")
                        if summary_text:
                            token_lines.append(f"[聚合后标题] {summary_text}\n")
                        else:
                            token_lines.append("[聚合后标题] （无标题）\n")
                        
                        # 立场（必需字段，中文化）
                        stance_raw = getattr(ev, "stance", "")
                        stance_zh = _zh_stance(stance_raw) if stance_raw else "证据不足"
                        token_lines.append(f"[立场] {stance_zh}\n")
                        # 对齐置信度（必需字段）
                        alignment_confidence = getattr(ev, "alignment_confidence", None)
                        if alignment_confidence is not None:
                            token_lines.append(f"[对齐置信度] {alignment_confidence:.2f}\n")
                        else:
                            token_lines.append("[对齐置信度] N/A\n")
                        
                        # 对齐权重（必需字段）
                        weight = getattr(ev, "weight", None)
                        if weight is not None:
                            token_lines.append(f"[对齐权重] {weight:.2f}\n")
                        else:
                            token_lines.append("[对齐权重] N/A\n")
                        
                        # 对齐理由（必需字段）
                        alignment_rationale = getattr(ev, "alignment_rationale", "")
                        if alignment_rationale:
                            token_lines.append(f"[对齐理由] {alignment_rationale}\n")
                        else:
                            token_lines.append("[对齐理由] （无对齐理由）\n")
                        token_lines.append("\n")

        # 逐条输出 token 事件
        for line in token_lines:
            yield _emit_sse_token(session_id, line)

        # 持久化中间态（写入 evidence_align）
        task = load_task(session_id) or {}
        input_text = str(task.get("input_text") or "")
        if not active_hash and input_text:
            active_hash = _hash_input_text(input_text)
        phases = _current_phases()
        phases["align"] = "done"
        phases["report"] = "idle"
        phases["simulation"] = "idle"
        phases["content"] = "idle"
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="evidence_align",
            status="done",
            payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in aligned]},
            meta={"source": "chat", "input_text_hash": active_hash},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="evidence_align",
            payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in aligned]},
            input_text=input_text,
        )
        chat_store.update_session_meta_fields(session_id, {"last_phase": "evidence_align", "last_task_id": session_id})

        # SSE stage: done
        yield _emit_sse_stage(session_id, "align_only", "done")

        # 最终 message 事件
        summary_content = f"证据对齐完成：已输出 {len(aligned)} 条聚合后证据。"
        if not aligned:
            summary_content = "证据对齐完成：未生成有效的聚合证据。"
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[ChatAction(type="command", label="继续生成报告", command="/report_only")] if aligned else [],
            references=[],
            meta={"phase": "evidence_align", "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return

    if tool == "report_only":
        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return
        args = ToolReportOnlyArgs.model_validate(args_dict)
        preferred_text = str(args.text or "").strip()
        active_hash = str(session_meta.get("input_text_hash") or "")
        if preferred_text:
            active_hash = _hash_input_text(preferred_text)
        align_payload = (
            _get_hash_phase(active_hash, "evidence_align")
            or _get_hash_phase(active_hash, "align")
            or get_phase_payload(session_id, "evidence_align")
            or get_phase_payload(session_id, "align")
            or {}
        )
        claims = [ClaimItem.model_validate(item) for item in (align_payload.get("claims") or []) if isinstance(item, dict)]
        evidences = [EvidenceItem.model_validate(item) for item in (align_payload.get("evidences") or []) if isinstance(item, dict)]
        input_text = preferred_text or _get_hash_input_text(active_hash)
        if not input_text:
            task = load_task(session_id) or {}
            input_text = str(task.get("input_text") or "")
        if not active_hash and input_text:
            active_hash = _hash_input_text(input_text)
        # 如果有 record_id，从历史记录回退
        if args.record_id:
            record = get_history(args.record_id)
            if record:
                report_obj = record.get("report") or {}
                claim_reports = report_obj.get("claim_reports") or []
                claims = [ClaimItem.model_validate((row or {}).get("claim")) for row in claim_reports if (row or {}).get("claim")]
                evidences = [
                    EvidenceItem.model_validate(item)
                    for row in claim_reports
                    for item in ((row or {}).get("evidences") or [])
                    if isinstance(item, dict)
                ]
                if not input_text:
                    input_text = str(record.get("input_text") or "")
        # 依赖检查：claims 和 evidences 必须有数据
        if (not claims or not evidences) and input_text:
            yield _emit_sse_token(session_id, "检测到缺少对齐中间态，正在自动补齐前置阶段（主张->证据->对齐）...\n")
            claims_payload = _get_hash_phase(active_hash, "claims") or get_phase_payload(session_id, "claims") or {}
            claims_data = claims_payload.get("claims") if isinstance(claims_payload, dict) else None
            claims = [ClaimItem.model_validate(item) for item in (claims_data or []) if isinstance(item, dict)]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n")
                for idx, claim in enumerate(claims, start=1):
                    claim_text = getattr(claim, "text", "")
                    claim_id = getattr(claim, "claim_id", f"C{idx}")
                    yield _emit_sse_token(session_id, f"{idx}. [{claim_id}] {claim_text}\n")
                yield _emit_sse_token(session_id, "\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )
            evidence_payload = _get_hash_phase(active_hash, "evidence_search") or get_phase_payload(session_id, "evidence_search") or {}
            evidence_data = evidence_payload.get("evidences") if isinstance(evidence_payload, dict) else None
            evidences = [EvidenceItem.model_validate(item) for item in (evidence_data or []) if isinstance(item, dict)]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(session_id, f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in evidences]},
                    input_text=input_text,
                )
            if claims and evidences:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    evidences = align_evidences(claims=claims, evidences=evidences)
                yield _emit_sse_token(session_id, f"【自动补齐-证据对齐结果】\n对齐证据数: {len(evidences)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in evidences]},
                    input_text=input_text,
                )

        if not claims or not evidences:
            dep = _build_missing_dependency_message(
                tool_name="report_only",
                detail="缺少对齐后的证据中间态。",
                suggestion="先执行 /align_only，或提供可复用的 record_id。",
            )
            yield from _emit_and_store(dep)
            return

        # SSE stage: running
        yield _emit_sse_stage(session_id, "report_only", "running")
        try:
            with llm_slot():
                report_dict = orchestrator.run_report(text=input_text, claims=claims, evidences=evidences)
            report = ReportResponse.model_validate(report_dict)
        except Exception as e:
            logger.error(f"[report_only] 报告生成失败: {e}")
            err_msg = ChatMessage(
                role="assistant",
                content=f"报告生成失败：{str(e)[:200]}。请稍后重试或检查配置。",
                actions=[ChatAction(type="command", label="重试", command="/report_only")],
                references=[],
            )
            yield from _emit_and_store(err_msg)
            return
        # SSE token 流式输出：报告详情块（概览 + 摘要 + 可疑点）
        token_lines = []
        token_lines.append("【报告详情】\n\n")

        # 部分 1: 报告概览
        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        scenario_zh = _SCENARIO_ZH.get(report.detected_scenario, report.detected_scenario)
        token_lines.append(f"[识别场景] {scenario_zh}\n")
        
        domains_zh = ", ".join([_DOMAIN_ZH.get(d, d) for d in report.evidence_domains])
        token_lines.append(f"[证据覆盖域] {domains_zh}\n")
        
        token_lines.append(f"[风险评分] {report.risk_score}/100\n")
        risk_level_zh = _RISK_LEVEL_ZH.get(report.risk_level, report.risk_level)
        token_lines.append(f"[风险等级] {risk_level_zh}\n")
        risk_label_zh = _RISK_LABEL_ZH.get(report.risk_label, report.risk_label)
        token_lines.append(f"[风险标签] {risk_label_zh}\n")
        token_lines.append("\n")

        # 部分 2: 综合摘要
        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        token_lines.append("[综合摘要]\n")
        summary_text = report.summary or "（无摘要）"
        token_lines.append(f"{summary_text}\n")
        token_lines.append("\n")

        # 部分 3: 可疑点列表
        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        token_lines.append("[可疑点]\n")
        if not report.suspicious_points:
            token_lines.append("  （无明显可疑点）\n")
        else:
            for idx, point in enumerate(report.suspicious_points, start=1):
                token_lines.append(f"  {idx}. {point}\n")
        token_lines.append("\n")

        # 逐条输出 token 事件
        for line in token_lines:
            yield _emit_sse_token(session_id, line)

        # 持久化中间态（不论 persist 开关，都写 session phase）
        phases = _current_phases()
        phases["report"] = "done"
        phases["simulation"] = "idle"
        phases["content"] = "idle"
        # persist 开关：只有显式 persist=True 时才写入历史记录
        record_id = ""
        if args.persist:
            record_id = save_report(input_text=input_text or "[无原文]", report=jsonable_encoder(report), detect_data=None)
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="report",
            status="done",
            payload={"report": report, "record_id": record_id} if record_id else {"report": report},
            meta={"source": "chat", "record_id": record_id} if record_id else {"source": "chat"},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="report",
            payload={"report": report.model_dump(), "record_id": record_id} if record_id else {"report": report.model_dump()},
            input_text=input_text,
        )
        
        session_meta_update = {"last_phase": "report", "last_task_id": session_id}
        if record_id:
            session_meta_update["bound_record_id"] = record_id
        chat_store.update_session_meta_fields(session_id, session_meta_update)

        # SSE stage: done
        yield _emit_sse_stage(session_id, "report_only", "done")

        # 最终 message 事件
        if args.persist and record_id:
            content_text = f"report_only 完成：已生成报告并写入历史记录 {record_id}。"
            actions = [
                ChatAction(type="command", label="仅执行舆情预演", command="/simulate"),
                ChatAction(type="command", label="仅生成应对内容", command="/content_generate"),
            ]
            references = [ChatReference(title=f"历史记录：{record_id}", href="/history", description="可在历史记录页查看")]
            meta = {"phase": "report", "record_id": record_id, "task_id": session_id}
        else:
            content_text = "report_only 完成：已生成报告详情（未写入历史记录）。"
            actions = [
                ChatAction(type="command", label="仅执行舆情预演", command="/simulate"),
                ChatAction(type="command", label="仅生成应对内容", command="/content_generate"),
            ]
            references = []
            meta = {"phase": "report", "task_id": session_id}
        msg = ChatMessage(
            role="assistant",
            content=content_text,
            actions=actions,
            references=references,
            meta=meta,
        )
        yield from _emit_and_store(msg)
        return

    if tool == "simulate":
        try:
            args = ToolSimulateArgs.model_validate(args_dict)
        except ValidationError:
            usage = ChatMessage(
                role="assistant",
                content="用法：/simulate [record_id]（自然语言场景可直接附文本）",
                actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                references=[],
            )
            yield from _emit_and_store(usage)
            return

        preferred_text = str(args.text or "").strip()
        active_hash = str(session_meta.get("input_text_hash") or "")
        if preferred_text:
            active_hash = _hash_input_text(preferred_text)
        report_payload = _get_hash_phase(active_hash, "report") or get_phase_payload(session_id, "report") or {}
        report_data = report_payload.get("report") if isinstance(report_payload, dict) else None
        record_id = str(report_payload.get("record_id") or args.record_id or session_meta.get("bound_record_id") or "")
        input_text = preferred_text or _get_hash_input_text(active_hash)
        if not input_text:
            task = load_task(session_id) or {}
            input_text = str(task.get("input_text") or "")
        if not active_hash and input_text:
            active_hash = _hash_input_text(input_text)

        if not isinstance(report_data, dict) and record_id:
            record = get_history(record_id)
            if record:
                report_data = record.get("report")
                if not input_text:
                    input_text = str(record.get("input_text") or "")

        if not isinstance(report_data, dict) and input_text:
            yield _emit_sse_token(session_id, "检测到缺少报告中间态，正在自动补齐前置阶段（主张->证据->对齐->报告）...\n")
            claims_payload = _get_hash_phase(active_hash, "claims") or get_phase_payload(session_id, "claims") or {}
            claims_data = claims_payload.get("claims") if isinstance(claims_payload, dict) else None
            claims = [ClaimItem.model_validate(item) for item in (claims_data or []) if isinstance(item, dict)]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n")
                for idx, claim in enumerate(claims, start=1):
                    claim_text = getattr(claim, "text", "")
                    claim_id = getattr(claim, "claim_id", f"C{idx}")
                    yield _emit_sse_token(session_id, f"{idx}. [{claim_id}] {claim_text}\n")
                yield _emit_sse_token(session_id, "\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )

            evidence_payload = _get_hash_phase(active_hash, "evidence_search") or get_phase_payload(session_id, "evidence_search") or {}
            evidence_data = evidence_payload.get("evidences") if isinstance(evidence_payload, dict) else None
            evidences = [EvidenceItem.model_validate(item) for item in (evidence_data or []) if isinstance(item, dict)]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(session_id, f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in evidences]},
                    input_text=input_text,
                )

            aligned = []
            if claims and evidences:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    aligned = align_evidences(claims=claims, evidences=evidences)
                yield _emit_sse_token(session_id, f"【自动补齐-证据对齐结果】\n对齐证据数: {len(aligned)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in aligned]},
                    input_text=input_text,
                )

            if claims and aligned:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    report_dict = orchestrator.run_report(text=input_text, claims=claims, evidences=aligned)
                report_obj_auto = ReportResponse.model_validate(report_dict)
                report_data = report_obj_auto.model_dump()
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-报告结果】\n风险标签: {report_obj_auto.risk_label}，风险分: {report_obj_auto.risk_score}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="report",
                    payload={"report": report_data},
                    input_text=input_text,
                )

        if not isinstance(report_data, dict):
            dep = _build_missing_dependency_message(
                tool_name="simulate",
                detail="缺少 report 中间态。",
                suggestion="先执行 /report_only（推荐：/report_only persist=true），或直接提供 record_id。",
            )
            yield from _emit_and_store(dep)
            return

        report_obj = ReportResponse.model_validate(report_data)
        sim_cache_key = _stable_hash_payload(
            {
                "record_id": record_id,
                "report": report_obj,
                "input_text": input_text,
            }
        )
        sim_cache_entry = session_meta.get("session_cache_simulate")
        if _is_cache_hit(sim_cache_entry, sim_cache_key):
            cached_sim_payload = _get_hash_phase(active_hash, "simulation") or get_phase_payload(session_id, "simulation") or {}
            cached_sim_data = cached_sim_payload.get("simulation") if isinstance(cached_sim_payload, dict) else None
            if isinstance(cached_sim_data, dict):
                sim = SimulateResponse.model_validate(cached_sim_data)
                yield _emit_sse_stage(session_id, "simulate", "running")
                yield _emit_sse_token(session_id, "命中会话缓存：复用最近一次舆情预演结果（未重复调用模型）。\n")
                yield _emit_sse_token(session_id, f"【舆情预演-情绪分布】\n情绪项: {len(sim.emotion_distribution)}，立场项: {len(sim.stance_distribution)}\n\n")
                yield _emit_sse_token(session_id, f"【舆情预演-叙事分支】\n分支数: {len(sim.narratives)}\n\n")
                yield _emit_sse_token(session_id, f"【舆情预演-引爆点】\n条目数: {len(sim.flashpoints)}\n\n")
                yield _emit_sse_token(session_id, f"【舆情预演-时间线】\n条目数: {len(sim.timeline or [])}\n\n")
                action_count = len((sim.suggestion or {}).actions or []) if sim.suggestion else 0
                yield _emit_sse_token(session_id, f"【舆情预演-应对建议】\n行动项: {action_count}\n\n")
                yield _emit_sse_stage(session_id, "simulate", "done")
                msg = ChatMessage(
                    role="assistant",
                    content="simulate 完成：命中会话缓存，已返回最近结果。",
                    actions=[ChatAction(type="command", label="继续生成应对内容", command="/content_generate")],
                    references=[],
                    meta={"phase": "simulation", "record_id": record_id, "task_id": session_id, "cache_hit": True},
                )
                yield from _emit_and_store(msg)
                return

        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return
        claims = [c.claim for c in report_obj.claim_reports]
        evidences = [ev for row in report_obj.claim_reports for ev in row.evidences]

        yield _emit_sse_stage(session_id, "simulate", "running")
        yield _emit_sse_token(session_id, "正在执行舆情预演（流式）...\n")

        accumulated: dict[str, Any] = {
            "emotion_distribution": {},
            "stance_distribution": {},
            "narratives": [],
            "flashpoints": [],
            "timeline": [],
            "suggestion": {"summary": "", "actions": []},
            "emotion_drivers": [],
            "stance_drivers": [],
        }

        for chunk in simulate_opinion_stream(
            text=input_text or report_obj.summary,
            claims=claims,
            evidences=evidences,
            report=report_obj,
            time_window_hours=24,
            platform="general",
            comments=[],
        ):
            stage = str((chunk or {}).get("stage") or "")
            data = (chunk or {}).get("data") if isinstance(chunk, dict) else {}
            if not isinstance(data, dict):
                data = {}

            token_lines: list[str] = []

            if stage == "emotion":
                emotion_distribution = data.get("emotion_distribution") or {}
                stance_distribution = data.get("stance_distribution") or {}
                emotion_drivers = data.get("emotion_drivers") or []
                stance_drivers = data.get("stance_drivers") or []

                accumulated["emotion_distribution"] = emotion_distribution
                accumulated["stance_distribution"] = stance_distribution
                accumulated["emotion_drivers"] = [str(x) for x in emotion_drivers if str(x).strip()]
                accumulated["stance_drivers"] = [str(x) for x in stance_drivers if str(x).strip()]

                token_lines.append("【舆情预演-情绪分布】\n")
                for k, v in (emotion_distribution.items() if isinstance(emotion_distribution, dict) else []):
                    try:
                        token_lines.append(f"[情绪] {k}: {float(v) * 100:.0f}%\n")
                    except Exception:
                        token_lines.append(f"[情绪] {k}: {v}\n")
                for k, v in (stance_distribution.items() if isinstance(stance_distribution, dict) else []):
                    try:
                        token_lines.append(f"[立场] {k}: {float(v) * 100:.0f}%\n")
                    except Exception:
                        token_lines.append(f"[立场] {k}: {v}\n")
                if accumulated["emotion_drivers"]:
                    token_lines.append(f"[情绪驱动] {'；'.join(accumulated['emotion_drivers'][:3])}\n")
                if accumulated["stance_drivers"]:
                    token_lines.append(f"[立场驱动] {'；'.join(accumulated['stance_drivers'][:3])}\n")
                token_lines.append("\n")

            elif stage == "narratives":
                narratives_data = data.get("narratives") or []
                accumulated["narratives"] = narratives_data if isinstance(narratives_data, list) else []

                token_lines.append("【舆情预演-叙事分支】\n")
                if not accumulated["narratives"]:
                    token_lines.append("（暂无叙事分支）\n")
                for idx, item in enumerate(accumulated["narratives"], start=1):
                    if not isinstance(item, dict):
                        continue
                    title = str(item.get("title") or f"叙事分支{idx}")
                    stance = str(item.get("stance") or "neutral")
                    probability = item.get("probability")
                    prob_text = "N/A"
                    if probability is not None:
                        try:
                            prob_text = f"{float(probability) * 100:.0f}%"
                        except Exception:
                            pass
                    keywords = item.get("trigger_keywords") or []
                    sample_message = str(item.get("sample_message") or "")

                    token_lines.append(f"{idx}. {title}（立场: {stance}，概率: {prob_text}）\n")
                    if isinstance(keywords, list) and keywords:
                        token_lines.append(f"   - 触发关键词: {'、'.join([str(k) for k in keywords[:5]])}\n")
                    if sample_message:
                        token_lines.append(f"   - 示例: {sample_message}\n")
                token_lines.append("\n")

            elif stage == "flashpoints":
                flashpoints = data.get("flashpoints") or []
                timeline = data.get("timeline") or []
                accumulated["flashpoints"] = [str(x) for x in flashpoints if str(x).strip()] if isinstance(flashpoints, list) else []
                accumulated["timeline"] = timeline if isinstance(timeline, list) else []

                token_lines.append("【舆情预演-引爆点】\n")
                if not accumulated["flashpoints"]:
                    token_lines.append("（暂无引爆点）\n")
                else:
                    for idx, fp in enumerate(accumulated["flashpoints"], start=1):
                        token_lines.append(f"{idx}. {fp}\n")
                token_lines.append("\n")

                token_lines.append("【舆情预演-时间线】\n")
                if not accumulated["timeline"]:
                    token_lines.append("（暂无时间线）\n")
                else:
                    for item in accumulated["timeline"]:
                        if not isinstance(item, dict):
                            continue
                        hour = item.get("hour")
                        event = str(item.get("event") or "")
                        expected_reach = str(item.get("expected_reach") or "")
                        token_lines.append(f"[T+{hour}h] {event}（预计触达: {expected_reach}）\n")
                token_lines.append("\n")

            elif stage == "suggestion":
                suggestion_data = data.get("suggestion") or {}
                accumulated["suggestion"] = suggestion_data if isinstance(suggestion_data, dict) else {"summary": "", "actions": []}

                token_lines.append("【舆情预演-应对建议】\n")
                summary = str((accumulated["suggestion"] or {}).get("summary") or "")
                if summary:
                    token_lines.append(f"[摘要] {summary}\n")
                actions = (accumulated["suggestion"] or {}).get("actions") or []
                if not isinstance(actions, list):
                    actions = []
                if not actions:
                    token_lines.append("（暂无应对建议）\n")
                for idx, action in enumerate(actions, start=1):
                    if not isinstance(action, dict):
                        continue
                    priority = str(action.get("priority") or "medium")
                    category = str(action.get("category") or "official")
                    action_text = str(action.get("action") or "")
                    timeline = str(action.get("timeline") or "")
                    responsible = str(action.get("responsible") or "")
                    token_lines.append(f"{idx}. [{priority}/{category}] {action_text}\n")
                    if timeline:
                        token_lines.append(f"   - 时间: {timeline}\n")
                    if responsible:
                        token_lines.append(f"   - 责任方: {responsible}\n")
                token_lines.append("\n")

            for line in token_lines:
                yield _emit_sse_token(session_id, line)

        sim = SimulateResponse.model_validate(accumulated)
        if record_id:
            update_simulation(record_id, sim.model_dump())

        phases = _current_phases()
        phases["simulation"] = "done"
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="simulation",
            status="done",
            payload={"simulation": sim.model_dump()},
            meta={"source": "chat", "record_id": record_id},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="simulation",
            payload={"simulation": sim.model_dump()},
            input_text=input_text,
        )
        chat_store.update_session_meta_fields(
            session_id,
            {"last_phase": "simulation", "last_task_id": session_id, "bound_record_id": record_id},
        )
        _save_session_cache_entry(session_id, "session_cache_simulate", sim_cache_key)
        yield _emit_sse_stage(session_id, "simulate", "done")
        msg = ChatMessage(
            role="assistant",
            content="simulate 完成：已生成舆情预演结果。",
            actions=[ChatAction(type="command", label="继续生成应对内容", command="/content_generate")],
            references=[],
            meta={"phase": "simulation", "record_id": record_id, "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return

    if tool == "content_generate":
        args = ToolContentGenerateArgs.model_validate(args_dict)
        operation = (args.operation or "generate").strip().lower()
        detail = (args.detail or "full").strip().lower()
        if detail not in {"brief", "full"}:
            detail = "full"

        def _content_block(title: str, body: str) -> list[str]:
            safe_title = title.replace(" ", "_").upper()
            return [
                f"-----BEGIN {safe_title}-----\n",
                f"{body}\n" if body else "（空）\n",
                "-----END-----\n\n",
            ]

        def _render_content_lines(content_resp: ContentGenerateResponse, detail_mode: str) -> list[str]:
            lines: list[str] = []
            faq_items = content_resp.faq or []
            scripts = content_resp.platform_scripts or []
            lines.append("【应对内容生成结果】\n")
            lines.append("[澄清稿] 3 个版本（短/中/长）\n")
            lines.append(f"[FAQ] {len(faq_items)} 条\n")
            lines.append(f"[平台话术] {len(scripts)} 条\n\n")
            if detail_mode == "brief":
                lines.extend(_content_block("clarification_short_preview", (content_resp.clarification.short or "")[:300]))
                if faq_items:
                    lines.extend(_content_block("faq_preview", f"Q: {faq_items[0].question}\nA: {faq_items[0].answer}"))
                if scripts:
                    lines.extend(_content_block("script_preview", f"[{scripts[0].platform}]\n{scripts[0].content}"))
                return lines

            lines.extend(_content_block("clarification_short", content_resp.clarification.short or ""))
            lines.extend(_content_block("clarification_medium", content_resp.clarification.medium or ""))
            lines.extend(_content_block("clarification_long", content_resp.clarification.long or ""))
            for idx, item in enumerate(faq_items, start=1):
                lines.extend(_content_block(f"faq_{idx}", f"Q: {item.question}\nA: {item.answer}"))
            for script in scripts:
                lines.extend(_content_block(f"script_{script.platform}", script.content))
            return lines
        active_hash = str(session_meta.get("input_text_hash") or "")
        preferred_text = str(args.text or "").strip()
        if preferred_text:
            active_hash = _hash_input_text(preferred_text)
        report_payload = _get_hash_phase(active_hash, "report") or ({} if preferred_text else (get_phase_payload(session_id, "report") or {}))
        simulation_payload = _get_hash_phase(active_hash, "simulation") or ({} if preferred_text else (get_phase_payload(session_id, "simulation") or {}))
        report_data = report_payload.get("report") if isinstance(report_payload, dict) else None
        simulation_data = simulation_payload.get("simulation") if isinstance(simulation_payload, dict) else None
        record_id = str(report_payload.get("record_id") or args.record_id or session_meta.get("bound_record_id") or "")
        input_text = preferred_text or _get_hash_input_text(active_hash)
        if not input_text:
            task = load_task(session_id) or {}
            input_text = str(task.get("input_text") or "")

        if not isinstance(report_data, dict) and record_id:
            record = get_history(record_id)
            if record:
                report_data = record.get("report")
                simulation_data = simulation_data or record.get("simulation")
                if not input_text:
                    input_text = str(record.get("input_text") or "")

        existing_content_payload = _get_hash_phase(active_hash, "content") or {}
        existing_content_data = existing_content_payload.get("content") if isinstance(existing_content_payload, dict) else None

        if operation == "show":
            if isinstance(existing_content_data, dict):
                content_resp_show = ContentGenerateResponse.model_validate(existing_content_data)
                yield _emit_sse_stage(session_id, "content_generate", "running")
                yield _emit_sse_token(session_id, "已加载当前会话中已生成的应对内容。\n")
                section = (args.section or "").strip().lower()
                variant = (args.variant or "").strip().lower()
                faq_range = (args.faq_range or "").strip()
                platforms = (args.platforms or "").strip().lower()
                custom_lines: list[str] = []
                if section == "clarification":
                    body_map = {
                        "short": content_resp_show.clarification.short or "",
                        "medium": content_resp_show.clarification.medium or "",
                        "long": content_resp_show.clarification.long or "",
                    }
                    chosen = body_map.get(variant or "short", body_map["short"])
                    custom_lines.extend(_content_block(f"clarification_{variant or 'short'}", chosen))
                elif section == "faq":
                    faq_items = content_resp_show.faq or []
                    start_idx = 1
                    end_idx = len(faq_items)
                    if "-" in faq_range:
                        left, right = faq_range.split("-", 1)
                        if left.strip().isdigit():
                            start_idx = max(1, int(left.strip()))
                        if right.strip().isdigit():
                            end_idx = max(start_idx, int(right.strip()))
                    for idx, item in enumerate(faq_items, start=1):
                        if idx < start_idx or idx > end_idx:
                            continue
                        custom_lines.extend(_content_block(f"faq_{idx}", f"Q: {item.question}\nA: {item.answer}"))
                    if not custom_lines:
                        custom_lines.extend(_content_block("faq", "未匹配到 FAQ 条目"))
                elif section == "scripts":
                    wanted = {x.strip() for x in platforms.split(",") if x.strip()} if platforms else set()
                    scripts = content_resp_show.platform_scripts or []
                    for script in scripts:
                        platform_name = str(script.platform)
                        if wanted and platform_name not in wanted:
                            continue
                        custom_lines.extend(_content_block(f"script_{platform_name}", script.content))
                    if not custom_lines:
                        custom_lines.extend(_content_block("scripts", "未匹配到平台话术"))

                lines_to_emit = custom_lines or _render_content_lines(content_resp_show, detail)
                for line in lines_to_emit:
                    yield _emit_sse_token(session_id, line)
                yield _emit_sse_stage(session_id, "content_generate", "done")
                show_msg = ChatMessage(
                    role="assistant",
                    content="content_show 完成：已展示已生成内容。",
                    actions=[ChatAction(type="command", label="完整查看", command="/content detail=full")],
                    references=[],
                    meta={"phase": "content", "record_id": record_id, "task_id": session_id, "cache_hit": True},
                )
                yield from _emit_and_store(show_msg)
                return

            no_show_msg = ChatMessage(
                role="assistant",
                content="当前会话暂无可展示的应对内容。请先执行 /content 或 /content_generate 生成。",
                actions=[ChatAction(type="command", label="立即生成", command="/content")],
                references=[],
            )
            yield from _emit_and_store(no_show_msg)
            return

        if (not args.force) and isinstance(existing_content_data, dict) and not isinstance(report_data, dict):
            content_resp_fallback = ContentGenerateResponse.model_validate(existing_content_data)
            yield _emit_sse_stage(session_id, "content_generate", "running")
            yield _emit_sse_token(session_id, "报告中间态缺失，已直接复用当前会话已有应对内容。\n")
            for line in _render_content_lines(content_resp_fallback, detail):
                yield _emit_sse_token(session_id, line)
            yield _emit_sse_stage(session_id, "content_generate", "done")
            fallback_msg = ChatMessage(
                role="assistant",
                content="content_generate 完成：已复用已有内容（未重复生成）。",
                actions=[ChatAction(type="command", label="强制重生成", command="/content force=true")],
                references=[],
                meta={"phase": "content", "record_id": record_id, "task_id": session_id, "cache_hit": True},
            )
            yield from _emit_and_store(fallback_msg)
            return

        if args.reuse_only and not isinstance(existing_content_data, dict):
            reuse_only_msg = ChatMessage(
                role="assistant",
                content="reuse_only=true：当前未命中可复用内容，已跳过生成。可使用 /content force=true 触发重生成。",
                actions=[ChatAction(type="command", label="强制重生成", command="/content force=true")],
                references=[],
            )
            yield from _emit_and_store(reuse_only_msg)
            return

        if not isinstance(report_data, dict) and input_text:
            yield _emit_sse_token(session_id, "检测到缺少报告中间态，正在自动补齐前置阶段（主张->证据->对齐->报告）...\n")
            claims_payload = _get_hash_phase(active_hash, "claims") or {}
            claims_data = claims_payload.get("claims") if isinstance(claims_payload, dict) else None
            claims = [ClaimItem.model_validate(item) for item in (claims_data or []) if isinstance(item, dict)]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )

            evidence_payload = _get_hash_phase(active_hash, "evidence_search") or {}
            evidence_data = evidence_payload.get("evidences") if isinstance(evidence_payload, dict) else None
            evidences = [EvidenceItem.model_validate(item) for item in (evidence_data or []) if isinstance(item, dict)]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(session_id, f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in evidences]},
                    input_text=input_text,
                )

            aligned: list[EvidenceItem] = []
            if claims and evidences:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    aligned = align_evidences(claims=claims, evidences=evidences)
                yield _emit_sse_token(session_id, f"【自动补齐-证据对齐结果】\n对齐证据数: {len(aligned)}\n\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={"claims": [c.model_dump() for c in claims], "evidences": [e.model_dump() for e in aligned]},
                    input_text=input_text,
                )

            if claims and aligned:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    report_dict = orchestrator.run_report(text=input_text, claims=claims, evidences=aligned)
                report_obj_auto = ReportResponse.model_validate(report_dict)
                report_data = report_obj_auto.model_dump()
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-报告结果】\n风险标签: {report_obj_auto.risk_label}，风险分: {report_obj_auto.risk_score}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="report",
                    payload={"report": report_data},
                    input_text=input_text,
                )

        if not isinstance(report_data, dict):
            dep = _build_missing_dependency_message(
                tool_name="content_generate",
                detail="缺少 report 中间态。",
                suggestion="先执行 /report_only（建议 /report_only persist=true），或在命令中提供 record_id。",
            )
            yield from _emit_and_store(dep)
            return

        style_raw = (args.style or "formal").strip().lower()
        style_enum = ClarificationStyle.FORMAL
        if style_raw == "friendly":
            style_enum = ClarificationStyle.FRIENDLY
        elif style_raw == "neutral":
            style_enum = ClarificationStyle.NEUTRAL

        content_cache_key = _stable_hash_payload(
            {
                "record_id": record_id,
                "report": report_data,
                "simulation": simulation_data,
                "input_text": input_text,
                "style": style_enum,
            }
        )
        existing_content_key = ""
        if isinstance(existing_content_payload, dict):
            existing_content_key = str(existing_content_payload.get("content_key") or "")
        can_reuse_existing = isinstance(existing_content_data, dict) and (
            existing_content_key == content_cache_key or not existing_content_key
        )

        if (not args.force) and can_reuse_existing:
            content_resp_existing = ContentGenerateResponse.model_validate(existing_content_data)
            yield _emit_sse_stage(session_id, "content_generate", "running")
            yield _emit_sse_token(session_id, "命中已生成内容：复用会话中的应对内容（未重复调用模型）。\n")
            for line in _render_content_lines(content_resp_existing, detail):
                yield _emit_sse_token(session_id, line)
            yield _emit_sse_stage(session_id, "content_generate", "done")
            msg_existing = ChatMessage(
                role="assistant",
                content="content_generate 完成：已复用当前会话内容。",
                actions=[
                    ChatAction(type="command", label="强制重生成", command="/content force=true"),
                    ChatAction(type="command", label="按模块查看", command="/content_show clarification short"),
                ],
                references=[],
                meta={"phase": "content", "record_id": record_id, "task_id": session_id, "cache_hit": True},
            )
            yield from _emit_and_store(msg_existing)
            return

        if args.reuse_only and not can_reuse_existing:
            reuse_only_msg = ChatMessage(
                role="assistant",
                content="reuse_only=true：当前未命中可复用内容，已跳过生成。可使用 /content force=true 触发重生成。",
                actions=[ChatAction(type="command", label="强制重生成", command="/content force=true")],
                references=[],
            )
            yield from _emit_and_store(reuse_only_msg)
            return

        if bool(session_meta.get("content_generation_in_progress")) and not args.force:
            in_progress_msg = ChatMessage(
                role="assistant",
                content="当前已有应对内容生成任务进行中，请稍后使用 /content 查看结果，避免重复生成。",
                actions=[ChatAction(type="command", label="查看当前内容", command="/content")],
                references=[],
            )
            yield from _emit_and_store(in_progress_msg)
            return

        content_cache_entry = session_meta.get("session_cache_content_generate")
        if (not args.force) and _is_cache_hit(content_cache_entry, content_cache_key):
            cached_content_payload = _get_hash_phase(active_hash, "content") or {}
            cached_content_data = cached_content_payload.get("content") if isinstance(cached_content_payload, dict) else None
            if isinstance(cached_content_data, dict):
                content_resp = ContentGenerateResponse.model_validate(cached_content_data)
                yield _emit_sse_stage(session_id, "content_generate", "running")
                yield _emit_sse_token(session_id, "命中会话缓存：复用最近一次应对内容结果（未重复调用模型）。\n")
                for line in _render_content_lines(content_resp, detail):
                    yield _emit_sse_token(session_id, line)
                yield _emit_sse_stage(session_id, "content_generate", "done")
                msg = ChatMessage(
                    role="assistant",
                    content="content_generate 完成：命中会话缓存，已返回最近结果。",
                    actions=[
                        ChatAction(type="command", label="查看完整内容", command="/content detail=full"),
                        ChatAction(type="link", label="打开应对内容", href="/content"),
                    ],
                    references=[],
                    meta={"phase": "content", "record_id": record_id, "task_id": session_id, "cache_hit": True},
                )
                yield from _emit_and_store(msg)
                return

        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return

        yield _emit_sse_stage(session_id, "content_generate", "running")
        yield _emit_sse_token(session_id, "正在生成应对内容（澄清稿 / FAQ / 多平台话术）...\n")
        chat_store.update_session_meta_fields(session_id, {"content_generation_in_progress": True})
        session_meta["content_generation_in_progress"] = True

        try:
            report_obj = ReportResponse.model_validate(report_data)
            content_req = ContentGenerateRequest(
                text=input_text or report_obj.summary,
                report=report_obj,
                simulation=simulation_data,
                style=style_enum,
                platforms=[Platform.WEIBO, Platform.WECHAT, Platform.SHORT_VIDEO],
                include_faq=True,
                faq_count=5,
            )
            content_resp = asyncio.run(generate_full_content(content_req))
        except Exception as e:
            chat_store.update_session_meta_fields(session_id, {"content_generation_in_progress": False})
            session_meta["content_generation_in_progress"] = False
            err_msg = ChatMessage(
                role="assistant",
                content=f"content_generate 失败：{str(e)[:200]}。可稍后重试，或先执行 /report_only persist=true 后再试。",
                actions=[ChatAction(type="command", label="重试", command="/content_generate")],
                references=[],
            )
            yield from _emit_and_store(err_msg)
            return

        clarification_versions = 3
        faq_count = len(content_resp.faq or [])
        platform_scripts_count = len(content_resp.platform_scripts or [])
        for line in _render_content_lines(content_resp, detail):
            yield _emit_sse_token(session_id, line)

        if record_id:
            update_content(record_id, jsonable_encoder(content_resp))

        phases = _current_phases()
        phases["content"] = "done"
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="content",
            status="done",
            payload={"content": jsonable_encoder(content_resp)},
            meta={"source": "chat", "record_id": record_id},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="content",
            payload={
                "content": jsonable_encoder(content_resp),
                "content_key": content_cache_key,
                "style": str(style_enum),
                "content_version": int(time.time()),
            },
            input_text=input_text,
        )
        chat_store.update_session_meta_fields(session_id, {"content_generation_in_progress": False})
        session_meta["content_generation_in_progress"] = False
        chat_store.update_session_meta_fields(
            session_id,
            {"last_phase": "content", "last_task_id": session_id, "bound_record_id": record_id},
        )
        _save_session_cache_entry(session_id, "session_cache_content_generate", content_cache_key)
        yield _emit_sse_stage(session_id, "content_generate", "done")
        msg = ChatMessage(
            role="assistant",
            content=(
                "content_generate 完成：已生成应对内容。\n"
                f"- 澄清稿：{clarification_versions} 个版本\n"
                f"- FAQ：{faq_count} 条\n"
                f"- 多平台话术：{platform_scripts_count} 条"
            ),
            actions=[
                ChatAction(type="command", label="查看完整内容", command="/content detail=full"),
                ChatAction(type="command", label="按模块查看", command="/content_show clarification short"),
                ChatAction(type="link", label="打开应对内容", href="/content"),
            ],
            references=[],
            meta={"phase": "content", "record_id": record_id, "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    """对话编排端点（V1：工具白名单编排的第一步，先非流式）。"""

    session_id = _ensure_session(payload.session_id)
    text = payload.text.strip()

    # 先落库用户消息（不阻塞主流程）
    try:
        chat_store.append_message(session_id, role="user", content=text)
    except Exception:
        # 落库失败不应阻塞用户流程
        pass

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="应对内容", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

    # /why <record_id>
    # 支持：若用户已在前端上下文中加载过历史记录，则可只输入 /why，record_id 从 context 兜底。
    if text.startswith("/why") or text.startswith("/explain"):
        parts = text.split()
        record_id = parts[1] if len(parts) >= 2 else ""
        if not record_id and payload.context:
            record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
        try:
            msg = run_why(ToolWhyArgs.model_validate({"record_id": record_id}))
        except ValidationError:
            msg = build_why_usage_message()
        try:
            chat_store.append_message(
                session_id,
                role="assistant",
                content=msg.content,
                actions=[a.model_dump() for a in msg.actions],
                references=[r.model_dump() for r in msg.references],
                meta=msg.meta,
            )
        except Exception:
            pass
        return ChatResponse(session_id=session_id, assistant_message=msg)

    # /more_evidence（record_id 可从 context 兜底）
    if text.startswith("/more_evidence") or text.startswith("/more"):
        record_id = ""
        if payload.context:
            record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
        try:
            msg = run_more_evidence(ToolMoreEvidenceArgs.model_validate({"record_id": record_id}))
        except ValidationError:
            msg = build_why_usage_message()
        try:
            chat_store.append_message(
                session_id,
                role="assistant",
                content=msg.content,
                actions=[a.model_dump() for a in msg.actions],
                references=[r.model_dump() for r in msg.references],
                meta=msg.meta,
            )
        except Exception:
            pass
        return ChatResponse(session_id=session_id, assistant_message=msg)

    # /rewrite [style]（record_id 可从 context 兜底）
    if text.startswith("/rewrite"):
        parts = text.split()
        style = parts[1] if len(parts) >= 2 else "short"
        record_id = ""
        if payload.context:
            record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
        try:
            msg = run_rewrite(ToolRewriteArgs.model_validate({"record_id": record_id, "style": style}))
        except ValidationError:
            msg = build_why_usage_message()
        try:
            chat_store.append_message(
                session_id,
                role="assistant",
                content=msg.content,
                actions=[a.model_dump() for a in msg.actions],
                references=[r.model_dump() for r in msg.references],
                meta=msg.meta,
            )
        except Exception:
            pass
        return ChatResponse(session_id=session_id, assistant_message=msg)

    # /list [N] 或 /history 或 /records
    if text.startswith("/list") or text.startswith("/history") or text.startswith("/records"):
        tool, args_dict = parse_tool(text)
        if tool != "list":
            msg = build_help_message()
        else:
            msg = run_list(ToolListArgs.model_validate(args_dict))
        try:
            chat_store.append_message(
                session_id,
                role="assistant",
                content=msg.content,
                actions=[a.model_dump() for a in msg.actions],
                references=[r.model_dump() for r in msg.references],
                meta=getattr(msg, "meta", None) or {},
            )
        except Exception:
            pass
        return ChatResponse(session_id=session_id, assistant_message=msg)

    if not _is_analyze_intent(text):
        msg = build_intent_clarify_message(text)
        try:
            chat_store.append_message(
                session_id,
                role="assistant",
                content=msg.content,
                actions=[a.model_dump() for a in msg.actions],
                references=[r.model_dump() for r in msg.references],
            )
        except Exception:
            pass
        return ChatResponse(session_id=session_id, assistant_message=msg)

    analyze_text = _extract_analyze_text(text)
    if not analyze_text:
        msg = ChatMessage(
            role="assistant",
            content="用法：/analyze <待分析文本>。",
            actions=base_actions,
            references=[],
        )
        return ChatResponse(session_id=session_id, assistant_message=msg)

    # 1) 风险快照
    with llm_slot():
        risk = detect_risk_snapshot(analyze_text)

    # 2) 主张
    with llm_slot():
        claims = orchestrator.run_claims(analyze_text, strategy=risk.strategy)

    # 3) 证据检索
    evidences = orchestrator.run_evidence(text=analyze_text, claims=claims, strategy=risk.strategy)

    # 4) 证据聚合与对齐
    with llm_slot():
        aligned = align_evidences(claims=claims, evidences=evidences, strategy=risk.strategy)

    # 5) 报告
    with llm_slot():
        report = orchestrator.run_report(text=analyze_text, claims=claims, evidences=aligned, strategy=risk.strategy)

    record_id = save_report(
        input_text=analyze_text,
        report=report,
        detect_data={
            "label": risk.label,
            "confidence": risk.confidence,
            "score": risk.score,
            "reasons": risk.reasons,
        },
    )

    try:
        chat_store.update_session_meta(session_id, "record_id", record_id)
        chat_store.update_session_meta(session_id, "bound_record_id", record_id)
    except Exception:
        pass

    top_refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录已保存：{record_id}",
            href="/history",
            description="可在历史记录页查看详情并回放（后续会支持在对话中直接绑定 record_id）。",
        )
    ]
    for item in aligned[:5]:
        if item.url and item.url.startswith("http"):
            top_refs.append(
                ChatReference(
                    title=item.title[:80] or item.url,
                    href=item.url,
                    description=f"立场: {item.stance} · 置信度: {item.alignment_confidence}",
                )
            )

    content = (
        "已完成一次全链路分析，并写入历史记录。\n\n"
        f"- 风险快照: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
        f"- 主张数: {len(claims)}\n"
        f"- 对齐证据数: {len(aligned)}\n"
        f"- 报告风险: {_zh_risk_label(report.get('risk_label'))}（{report.get('risk_score')}）\n"
        f"- 场景: {_zh_scenario(report.get('detected_scenario'))}\n\n"
        "提示：下一步将对接对话工作台的‘加载该 record_id 到上下文’以实现真正追问与迭代。"
    )

    analyze_actions = base_actions + [
        ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
        ChatAction(type="command", label="为什么这样判定", command=f"/why {record_id}"),
    ]

    msg = ChatMessage(
        role="assistant",
        content=content,
        actions=analyze_actions,
        references=top_refs,
    )

    try:
        chat_store.append_message(
            session_id,
            role="assistant",
            content=msg.content,
            actions=[a.model_dump() for a in msg.actions],
            references=[r.model_dump() for r in msg.references],
            meta={"record_id": record_id},
        )
    except Exception:
        pass
    return ChatResponse(session_id=session_id, assistant_message=msg)


@router.post("/sessions", response_model=ChatSession)
def create_chat_session(payload: ChatSessionCreateRequest) -> ChatSession:
    created = chat_store.create_session(title=payload.title, meta=payload.meta)
    return ChatSession(**created)


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_chat_sessions(limit: int = 20) -> ChatSessionListResponse:
    sessions = [ChatSession(**s) for s in chat_store.list_sessions(limit=limit)]
    return ChatSessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}", response_model=ChatSessionDetailResponse)
def get_chat_session_detail(session_id: str, limit: int = 50) -> ChatSessionDetailResponse:
    sess = chat_store.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    messages = chat_store.list_messages(session_id, limit=limit)
    return ChatSessionDetailResponse(
        session=ChatSession(**sess),
        messages=[ChatMessage(**m) for m in messages],
    )


@router.post("/sessions/{session_id}/messages/stream")
def chat_session_stream(session_id: str, payload: ChatMessageCreateRequest) -> StreamingResponse:
    """V2 会话化 SSE：追加用户消息 -> 工具白名单编排 -> 逐步输出 -> 写入 assistant 消息。"""

    sess = chat_store.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    text = payload.text.strip()

    # 先落库 user message
    try:
        chat_store.append_message(session_id, role="user", content=text, meta={"context": payload.context})
    except Exception:
        pass

    def event_generator() -> Iterator[str]:
        try:
            session_meta = chat_store.get_session_meta(session_id)
            tool, args_dict = parse_tool(text, session_meta=session_meta)
            ctx = payload.context or {}

            if tool in {"claims_only", "evidence_only", "align_only", "report_only", "simulate", "content_generate"}:
                for line in _handle_single_skill_tool(session_id=session_id, tool=tool, args_dict=args_dict, session_meta=session_meta):
                    yield line
                return

            if tool == "help":
                if bool(args_dict.get("clarify")):
                    msg = build_intent_clarify_message(str(args_dict.get("text") or text))
                else:
                    msg = build_help_message()
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "load_history":
                args = ToolLoadHistoryArgs.model_validate(args_dict)
                msg = run_load_history(args)
                if msg.meta and msg.meta.get("record_id"):
                    try:
                        chat_store.update_session_meta(session_id, "bound_record_id", msg.meta["record_id"])
                    except Exception:
                        pass
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "list":
                args = ToolListArgs.model_validate(args_dict)
                msg = run_list(args)
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "why":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolWhyArgs.model_validate(args_dict)
                    msg = run_why(args)
                except ValidationError:
                    msg = build_why_usage_message()
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "more_evidence":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolMoreEvidenceArgs.model_validate(args_dict)
                    msg = run_more_evidence(args)
                except ValidationError:
                    msg = build_why_usage_message()
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "rewrite":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolRewriteArgs.model_validate(args_dict)
                    msg = run_rewrite(args)
                except ValidationError:
                    msg = build_why_usage_message()
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "compare":
                try:
                    args = ToolCompareArgs.model_validate(args_dict)
                    msg = run_compare(args)
                except ValidationError:
                    msg = ChatMessage(
                        role="assistant",
                        content="用法：/compare <record_id_1> <record_id_2>\n\n"
                        "例如：/compare rec_abc123 rec_def456",
                        actions=[ChatAction(type="command", label="列出最近记录", command="/list")],
                        references=[],
                    )
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "deep_dive":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolDeepDiveArgs.model_validate(args_dict)
                    msg = run_deep_dive(args)
                except ValidationError:
                    msg = ChatMessage(
                        role="assistant",
                        content="用法：/deep_dive <record_id> [focus] [claim_index]\n\n"
                        "- focus 可选：general（默认）/evidence/claims/timeline/sources\n"
                        "- claim_index：指定深入分析第几条主张（从0开始）\n\n"
                        "例如：/deep_dive rec_abc123 evidence",
                        actions=[ChatAction(type="command", label="列出最近记录", command="/list")],
                        references=[],
                    )
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            validation = validate_tool_call(tool, args_dict)
            if not validation.is_valid:
                msg = ChatMessage(
                    role="assistant",
                    content=f"参数校验失败：\n- " + "\n- ".join(validation.errors) + "\n\n请检查输入后重试。",
                    actions=[ChatAction(type="command", label="查看帮助", command="/help")],
                    references=[],
                )
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if validation.warnings:
                warning_prefix = build_guardrails_warning_message(validation.warnings)
                yield f"data: {ChatStreamEvent(type='token', data={'content': warning_prefix, 'session_id': session_id}).model_dump_json()}\n\n"

            args_dict = validation.args

            # tool == analyze
            args = ToolAnalyzeArgs.model_validate(args_dict)
            analyze_text = args.text

            # pipeline-state：把 chat 驱动的分析写入 phase snapshot，支持刷新恢复/继续
            phases_state: dict[str, str] = {
                "detect": "idle",
                "claims": "idle",
                "evidence": "idle",
                "report": "idle",
                "simulation": "idle",
                "content": "idle",
            }

            # 开始 token（让前端立即出现响应）
            yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 风险快照
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'risk', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 风险快照：计算中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["detect"] = "running"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="detect",
                status="running",
                payload=None,
                meta={"source": "chat"},
            )
            with llm_slot():
                risk = detect_risk_snapshot(analyze_text)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险快照：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'risk', 'status': 'done'}).model_dump_json()}\n\n"
            risk_reasons = [str(item) for item in (risk.reasons or []) if str(item).strip()]
            strategy = risk.strategy
            risk_detail_lines = [
                f"[风险详情] 标签: {_zh_risk_label(risk.label)} | 分数: {risk.score} | 置信度: {risk.confidence:.2f}",
                (
                    f"[风险详情] 策略: claims={strategy.max_claims} | evidence/claim={strategy.evidence_per_claim}"
                    if strategy
                    else "[风险详情] 策略: 使用默认策略"
                ),
            ]
            if strategy and strategy.risk_reason:
                risk_detail_lines.append(f"[风险详情] 风险策略: {_truncate_text(strategy.risk_reason, 72)}")
            for reason in risk_reasons[:3]:
                risk_detail_lines.append(f"[风险详情] - {_truncate_text(reason, 72)}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(risk_detail_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["detect"] = "done"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="detect",
                status="done",
                payload={"label": risk.label, "score": risk.score},
                meta={"source": "chat"},
            )

            # 主张
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'claims', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 主张抽取：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["claims"] = "running"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="claims",
                status="running",
                payload=None,
                meta={"source": "chat"},
            )
            with llm_slot():
                claims = orchestrator.run_claims(analyze_text, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 主张抽取：完成（{len(claims)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'claims', 'status': 'done'}).model_dump_json()}\n\n"
            claim_lines: list[str] = []
            for idx, claim in enumerate(claims, start=1):
                claim_text = str(getattr(claim, "claim_text", "") or "").strip()
                claim_id = str(getattr(claim, "claim_id", f"c{idx}") or f"c{idx}").upper()
                claim_lines.append(f"[主张详情] {claim_id}：{claim_text}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(claim_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["claims"] = "done"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="claims",
                status="done",
                payload={"count": len(claims)},
                meta={"source": "chat"},
            )

            # 证据检索
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_search', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 联网检索证据：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["evidence"] = "running"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="evidence",
                status="running",
                payload=None,
                meta={"source": "chat"},
            )
            evidences = orchestrator.run_evidence(text=analyze_text, claims=claims, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_search', 'status': 'done'}).model_dump_json()}\n\n"
            evidence_lines = ["【原始检索证据】"]
            for idx, claim in enumerate(claims, start=1):
                if idx > 1:
                    evidence_lines.append(_CLAIM_SEPARATOR)
                claim_id = str(getattr(claim, "claim_id", f"c{idx}") or f"c{idx}").upper()
                claim_text = str(getattr(claim, "claim_text", "") or "").strip()
                evidence_lines.append(f"[主张 {claim_id}] {claim_text}")

                related = [ev for ev in evidences if str(getattr(ev, "claim_id", "")) == str(getattr(claim, "claim_id", ""))]
                if not related:
                    evidence_lines.append("  [证据] 无")
                    continue

                for evidence_idx, ev in enumerate(related, start=1):
                    title = str(getattr(ev, "title", "") or getattr(ev, "summary", "") or "无").strip()
                    link = str(getattr(ev, "url", "") or "无")
                    summary = _truncate_text(
                        getattr(ev, "summary", "") or getattr(ev, "raw_snippet", "") or "无",
                        120,
                    )
                    evidence_lines.append(f"  [证据 {evidence_idx}]")
                    evidence_lines.append(f"    [标题] {title}")
                    evidence_lines.append(f"    [来源链接] {link}")
                    evidence_lines.append(f"    [摘要] {summary}")
                    if evidence_idx < len(related):
                        evidence_lines.append(f"    {_EVIDENCE_SEPARATOR}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(evidence_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 证据聚合与对齐
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_align', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 证据聚合与对齐：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                aligned = align_evidences(claims=claims, evidences=evidences, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_align', 'status': 'done'}).model_dump_json()}\n\n"
            align_lines = ["【聚合后证据】"]
            for idx, claim in enumerate(claims, start=1):
                if idx > 1:
                    align_lines.append(_CLAIM_SEPARATOR)
                claim_id = str(getattr(claim, "claim_id", f"c{idx}") or f"c{idx}").upper()
                claim_text = str(getattr(claim, "claim_text", "") or "").strip()
                align_lines.append(f"[主张 {claim_id}] {claim_text}")

                related = [ev for ev in aligned if str(getattr(ev, "claim_id", "")) == str(getattr(claim, "claim_id", ""))]
                if not related:
                    align_lines.append("  [聚合证据] 无")
                    continue

                for evidence_idx, ev in enumerate(related, start=1):
                    merged_title = str(
                        getattr(ev, "summary", "") if getattr(ev, "source_type", "") == "web_summary" else getattr(ev, "title", "")
                    ).strip()
                    stance_text = _zh_stance(getattr(ev, "stance", ""))
                    conf = getattr(ev, "alignment_confidence", None)
                    conf_text = f"{float(conf):.2f}" if isinstance(conf, (int, float)) else "无"
                    weight = getattr(ev, "source_weight", None)
                    weight_text = f"{float(weight):.2f}" if isinstance(weight, (int, float)) else "无"
                    rationale = _truncate_text(getattr(ev, "alignment_rationale", "") or "无", 120)

                    align_lines.append(f"  [聚合证据 {evidence_idx}]")
                    align_lines.append(f"    [聚合后标题] {merged_title or '无'}")
                    align_lines.append(f"    [立场] {stance_text}")
                    align_lines.append(f"    [对齐置信度] {conf_text}")
                    align_lines.append(f"    [对齐权重] {weight_text}")
                    align_lines.append(f"    [对齐理由] {rationale}")
                    if evidence_idx < len(related):
                        align_lines.append(f"    {_EVIDENCE_SEPARATOR}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(align_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["evidence"] = "done"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="evidence",
                status="done",
                payload={"aligned_count": len(aligned)},
                meta={"source": "chat"},
            )

            # 报告
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'report', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：生成中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            phases_state["report"] = "running"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="report",
                status="running",
                payload=None,
                meta={"source": "chat"},
            )
            with llm_slot():
                report = orchestrator.run_report(
                    text=analyze_text,
                    claims=claims,
                    evidences=aligned,
                    strategy=risk.strategy,
                )
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：完成\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'report', 'status': 'done'}).model_dump_json()}\n\n"
            suspicious_points = [str(item) for item in (report.get("suspicious_points") or []) if str(item).strip()]
            evidence_domains = [str(item) for item in (report.get("evidence_domains") or []) if str(item).strip()]
            scenario_zh = _zh_scenario(report.get("detected_scenario"))
            evidence_domains_zh = [d for d in (_zh_domain(item) for item in evidence_domains) if d]
            report_lines = [
                f"[报告详情] 风险: {_zh_risk_label(report.get('risk_label'))} | score={report.get('risk_score')} | level={_zh_risk_level(report.get('risk_level'))}",
                f"[报告详情] 场景: {scenario_zh} | 证据域: {('、'.join(evidence_domains_zh) if evidence_domains_zh else '无')}",
                f"[报告详情] 摘要: {str(report.get('summary', '') or '').strip()}",
            ]
            if suspicious_points:
                report_lines.append("[报告详情] 可疑点:")
                for point in suspicious_points:
                    report_lines.append(f"- {point}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(report_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"

            record_id = save_report(
                input_text=analyze_text,
                report=report,
                detect_data={
                    "label": risk.label,
                    "confidence": risk.confidence,
                    "score": risk.score,
                    "reasons": risk.reasons,
                },
            )

            try:
                chat_store.update_session_meta(session_id, "record_id", record_id)
                chat_store.update_session_meta(session_id, "bound_record_id", record_id)
            except Exception:
                pass

            phases_state["report"] = "done"
            upsert_phase_snapshot(
                task_id=session_id,
                input_text=analyze_text,
                phases=phases_state,
                phase="report",
                status="done",
                payload={
                    "risk_label": report.get("risk_label"),
                    "risk_score": report.get("risk_score"),
                    "record_id": record_id,
                },
                meta={"source": "chat", "record_id": record_id},
            )

            top_refs: list[ChatReference] = [
                ChatReference(
                    title=f"历史记录已保存：{record_id}",
                    href="/history",
                    description="可在历史记录页查看详情并回放（后续会支持在对话中直接绑定 record_id）。",
                )
            ]
            for item in aligned[:5]:
                if item.url and item.url.startswith("http"):
                    top_refs.append(
                        ChatReference(
                            title=item.title[:80] or item.url,
                            href=item.url,
                            description=f"立场: {item.stance} · 置信度: {item.alignment_confidence}",
                        )
                    )

            msg = ChatMessage(
                role="assistant",
                content=(
                    "已完成一次全链路分析，并写入历史记录。\n\n"
                    f"- 风险快照: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
                    f"- 主张数: {len(claims)}\n"
                    f"- 对齐证据数: {len(aligned)}\n"
                    f"- 报告风险: {_zh_risk_label(report.get('risk_label'))}（{report.get('risk_score')}）\n"
                    f"- 场景: {_zh_scenario(report.get('detected_scenario'))}\n\n"
                    "提示：可使用下方命令把本次 record_id 加载到前端上下文进行追问。"
                ),
                actions=[
                    ChatAction(type="link", label="打开对话工作台", href="/chat"),
                    ChatAction(type="link", label="检测结果", href="/result"),
                    ChatAction(type="link", label="历史记录", href="/history"),
                    ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
                    ChatAction(type="command", label="为什么这样判定", command=f"/why {record_id}"),
                ],
                references=top_refs,
                meta={"record_id": record_id},
            )

            try:
                chat_store.append_message(
                    session_id,
                    role="assistant",
                    content=msg.content,
                    actions=[a.model_dump() for a in msg.actions],
                    references=[r.model_dump() for r in msg.references],
                    meta={"record_id": record_id},
                )
            except Exception:
                pass

            event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
            yield f"data: {event.model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
        except Exception as e:
            err = ChatStreamEvent(type="error", data={"session_id": session_id, "message": str(e)})
            yield f"data: {err.model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"

    return StreamingResponse(
        iter(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )


@router.post("/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """SSE 流式对话（V1：对齐 /chat 的最小工具编排，逐步输出 token + 最终结构化 message）。
    **DEPRECATED**: 建议使用 POST /chat/sessions/{session_id}/messages/stream (V2)
    事件格式：data: {"type":..., "data":...}\n\n
    """

    session_id = _ensure_session(payload.session_id)
    text = payload.text.strip()

    # 先落库用户消息（不阻塞主流程）
    try:
        chat_store.append_message(session_id, role="user", content=text, meta={"context": payload.context})
    except Exception:
        pass

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="应对内容", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

    def event_generator() -> Iterator[str]:
        try:
            # 0) /why <record_id>
            if text.startswith("/why") or text.startswith("/explain"):
                parts = text.split()
                record_id = parts[1] if len(parts) >= 2 else ""
                if not record_id and payload.context:
                    record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
                try:
                    msg = run_why(ToolWhyArgs.model_validate({"record_id": record_id}))
                except ValidationError:
                    msg = build_why_usage_message()
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                _safe_append_message(session_id, msg)
                return

            # 0.05) /more_evidence
            if text.startswith("/more_evidence") or text.startswith("/more"):
                record_id = ""
                if payload.context:
                    record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
                try:
                    msg = run_more_evidence(ToolMoreEvidenceArgs.model_validate({"record_id": record_id}))
                except ValidationError:
                    msg = build_why_usage_message()
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            # 0.06) /rewrite
            if text.startswith("/rewrite"):
                parts = text.split()
                style = parts[1] if len(parts) >= 2 else "short"
                record_id = ""
                if payload.context:
                    record_id = str(payload.context.get("record_id") or payload.context.get("recordId") or "")
                try:
                    msg = run_rewrite(ToolRewriteArgs.model_validate({"record_id": record_id, "style": style}))
                except ValidationError:
                    msg = build_why_usage_message()
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            # 0.1) /list [N] 或 /history 或 /records
            if text.startswith("/list") or text.startswith("/history") or text.startswith("/records"):
                tool, args_dict = parse_tool(text)
                if tool != "list":
                    msg = build_help_message()
                else:
                    msg = run_list(ToolListArgs.model_validate(args_dict))
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                _safe_append_message(session_id, msg)
                return

            # 0) 非分析意图：直接返回结构化 message（仍走 SSE 通道）
            if not _is_analyze_intent(text):
                msg = build_intent_clarify_message(text)
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"

                try:
                    chat_store.append_message(
                        session_id,
                        role="assistant",
                        content=msg.content,
                        actions=[a.model_dump() for a in msg.actions],
                        references=[r.model_dump() for r in msg.references],
                    )
                except Exception:
                    pass
                return

            analyze_text = _extract_analyze_text(text)
            if not analyze_text:
                msg = ChatMessage(
                    role="assistant",
                    content="用法：/analyze <待分析文本>。",
                    actions=base_actions,
                    references=[],
                )
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"

                try:
                    chat_store.append_message(
                        session_id,
                        role="assistant",
                        content=msg.content,
                        actions=[a.model_dump() for a in msg.actions],
                        references=[r.model_dump() for r in msg.references],
                    )
                except Exception:
                    pass
                return

            # 1) 开始提示（让前端立即出现响应）
            yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 2) 风险快照
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 风险快照：计算中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                risk = detect_risk_snapshot(analyze_text)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险快照：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 3) 主张
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 主张抽取：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                claims = orchestrator.run_claims(analyze_text, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 主张抽取：完成（{len(claims)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 4) 证据检索
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 联网检索证据：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            evidences = orchestrator.run_evidence(text=analyze_text, claims=claims, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 5) 证据聚合与对齐
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 证据聚合与对齐：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                aligned = align_evidences(claims=claims, evidences=evidences, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            # 6) 报告
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：生成中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                report = orchestrator.run_report(
                    text=analyze_text,
                    claims=claims,
                    evidences=aligned,
                    strategy=risk.strategy,
                )
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：完成\n', 'session_id': session_id}).model_dump_json()}\n\n"

            record_id = save_report(
                input_text=analyze_text,
                report=report,
                detect_data={
                    "label": risk.label,
                    "confidence": risk.confidence,
                    "score": risk.score,
                    "reasons": risk.reasons,
                },
            )

            top_refs: list[ChatReference] = [
                ChatReference(
                    title=f"历史记录已保存：{record_id}",
                    href="/history",
                    description="可在历史记录页查看详情并回放（后续会支持在对话中直接绑定 record_id）。",
                )
            ]
            for item in aligned[:5]:
                if item.url and item.url.startswith("http"):
                    top_refs.append(
                        ChatReference(
                            title=item.title[:80] or item.url,
                            href=item.url,
                            description=f"立场: {item.stance} · 置信度: {item.alignment_confidence}",
                        )
                    )

            content = (
                "已完成一次全链路分析，并写入历史记录。\n\n"
                f"- 风险快照: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
                f"- 主张数: {len(claims)}\n"
                f"- 对齐证据数: {len(aligned)}\n"
                f"- 报告风险: {_zh_risk_label(report.get('risk_label'))}（{report.get('risk_score')}）\n"
                f"- 场景: {_zh_scenario(report.get('detected_scenario'))}\n\n"
                "提示：可使用下方命令把本次 record_id 加载到前端上下文进行追问。"
            )

            analyze_actions = base_actions + [
                ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
                ChatAction(type="command", label="为什么这样判定", command=f"/why {record_id}"),
            ]

            msg = ChatMessage(
                role="assistant",
                content=content,
                actions=analyze_actions,
                references=top_refs,
            )
            event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
            yield f"data: {event.model_dump_json()}\n\n"

            try:
                chat_store.append_message(
                    session_id,
                    role="assistant",
                    content=msg.content,
                    actions=[a.model_dump() for a in msg.actions],
                    references=[r.model_dump() for r in msg.references],
                    meta={"record_id": record_id},
                )
            except Exception:
                pass

            yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
        except Exception as e:
            err = ChatStreamEvent(type="error", data={"session_id": session_id, "message": str(e)})
            yield f"data: {err.model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"

    return StreamingResponse(
        iter(event_generator()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Transfer-Encoding": "chunked",
        },
    )
