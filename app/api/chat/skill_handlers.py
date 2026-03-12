import asyncio
import time
from typing import Any, Iterator, cast

from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError

from app.core.concurrency import llm_slot
from app.core.logger import get_logger
from app.orchestrator import orchestrator
from app.schemas.chat import ChatAction, ChatMessage, ChatReference
from app.schemas.detect import (
    ClaimItem,
    ClarificationStyle,
    ContentGenerateRequest,
    ContentGenerateResponse,
    EvidenceItem,
    Platform,
    ReportResponse,
    SimulateResponse,
)
from app.services import chat_store
from app.services.content_generation import generate_full_content
from app.services.history_store import (
    get_history,
    save_report,
    update_content,
    update_simulation,
)
from app.services.opinion_simulation import simulate_opinion_stream
from app.services.pipeline import align_evidences
from app.services.pipeline_state_store import (
    get_phase_payload,
    load_task,
    upsert_phase_snapshot,
)
from app.services.chat_orchestrator import (
    ToolAlignOnlyArgs,
    ToolClaimsOnlyArgs,
    ToolContentGenerateArgs,
    ToolEvidenceOnlyArgs,
    ToolReportOnlyArgs,
    ToolSimulateArgs,
)

from .formatters import (
    _CLAIM_SEPARATOR,
    _DOMAIN_ZH,
    _EVIDENCE_SEPARATOR,
    _RISK_LABEL_ZH,
    _RISK_LEVEL_ZH,
    _SCENARIO_ZH,
    _STANCE_ZH,
    _truncate_text,
    _zh_stance,
)
from .session_helpers import (
    _build_missing_dependency_message,
    _hash_input_text,
    _is_cache_hit,
    _save_session_cache_entry,
    _session_hash_bucket_limit,
    _session_llm_max_calls,
    _session_tool_max_calls,
    _stable_hash_payload,
)
from .sse_helpers import (
    _emit_sse_done,
    _emit_sse_error,
    _emit_sse_message,
    _emit_sse_stage,
    _emit_sse_token,
    _safe_append_message,
)

logger = get_logger(__name__)


def _handle_single_skill_tool(
    *,
    session_id: str,
    tool: str,
    args_dict: dict[str, Any],
    session_meta: dict[str, Any],
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
        chat_store.update_session_meta_fields(
            session_id, {"phase_payload_buckets": trimmed}
        )
        session_meta["phase_payload_buckets"] = trimmed

    def _store_hash_phase(
        *, input_hash: str, phase: str, payload: dict[str, Any], input_text: str
    ) -> None:
        if not input_hash:
            return
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = (
            cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        )
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
        bucket: dict[str, Any] = (
            cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        )
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
        bucket: dict[str, Any] = (
            cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        )
        payload = bucket.get(phase)
        return payload if isinstance(payload, dict) else {}

    def _get_hash_input_text(input_hash: str) -> str:
        if not input_hash:
            return ""
        buckets = _normalize_hash_buckets()
        raw_bucket = buckets.get(input_hash)
        bucket: dict[str, Any] = (
            cast(dict[str, Any], raw_bucket) if isinstance(raw_bucket, dict) else {}
        )
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
        chat_store.update_session_meta_fields(
            session_id, {"tool_call_count": current + 1}
        )
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
        chat_store.update_session_meta_fields(
            session_id, {"llm_call_count": current + 1}
        )
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

        yield _emit_sse_stage(session_id, "claims_only", "running")
        yield _emit_sse_token(session_id, "正在分析文本并提取核心主张...\n")
        input_hash = _hash_input_text(input_text)
        _clear_hash_phases(
            input_hash,
            [
                "evidence_search",
                "evidence",
                "evidence_align",
                "align",
                "report",
                "simulation",
                "content",
            ],
        )
        with llm_slot():
            claims = orchestrator.run_claims(input_text)
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

        for line in token_lines:
            yield _emit_sse_token(session_id, line)

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

        yield _emit_sse_stage(session_id, "claims_only", "done")

        summary_content = (
            f"主张抽取完成：已提取 {len(claims)} 条主张并保存到 session 中间态。"
        )
        if not claims:
            summary_content = (
                "主张抽取完成：未提取到有效主张（可能文本不包含明确事实陈述）。"
            )
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[
                ChatAction(
                    type="command",
                    label="继续证据检索",
                    command=f"/evidence_only {input_text}",
                )
            ]
            if claims
            else [],
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
        claims_data = (
            claims_payload.get("claims") if isinstance(claims_payload, dict) else None
        )
        claims: list[ClaimItem] = []
        source_desc = "session"
        if isinstance(claims_data, list):
            claims = [ClaimItem.model_validate(item) for item in claims_data]
        if not claims and input_text:
            llm_budget_msg = _check_and_bump_llm_budget()
            if llm_budget_msg is not None:
                yield from _emit_and_store(llm_budget_msg)
                return
            yield _emit_sse_token(
                session_id, "检测到缺少主张中间态，已自动执行主张抽取前置阶段...\n"
            )
            with llm_slot():
                claims = orchestrator.run_claims(input_text)
            yield _emit_sse_token(
                session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n"
            )
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
                meta={
                    "source": "chat",
                    "input_text_hash": input_hash,
                    "auto_planned": True,
                },
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
        if not claims and args.record_id:
            record = get_history(args.record_id)
            if record:
                reports = (record.get("report") or {}).get("claim_reports") or []
                claims = [
                    ClaimItem.model_validate((row or {}).get("claim"))
                    for row in reports
                    if (row or {}).get("claim")
                ]
                source_desc = "record_id"
        if not claims:
            dep = _build_missing_dependency_message(
                tool_name="evidence_only",
                detail="缺少可用 claims 中间态。",
                suggestion="先执行 /claims_only <文本>，或提供含 claims 的 record_id。",
            )
            yield from _emit_and_store(dep)
            return
        _clear_hash_phases(
            input_hash, ["evidence_align", "align", "report", "simulation", "content"]
        )

        yield _emit_sse_stage(session_id, "evidence_only", "running")

        evidences = orchestrator.run_evidence(text=input_text, claims=claims)
        token_lines = []
        token_lines.append("【原始检索证据】\n\n")
        if not evidences:
            token_lines.append("未检索到有效证据。\n")
        else:
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

        for line in token_lines:
            yield _emit_sse_token(session_id, line)

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

        yield _emit_sse_stage(session_id, "evidence_only", "done")

        summary_content = f"证据检索完成：复用 {source_desc} 的 claims，检索到 {len(evidences)} 条证据并保存到 session 中间态。"
        if not evidences:
            summary_content = "证据检索完成：未检索到有效证据。"
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[
                ChatAction(type="command", label="继续证据对齐", command="/align_only")
            ]
            if evidences
            else [],
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
        evidence_payload = (
            _get_hash_phase(active_hash, "evidence_search")
            or _get_hash_phase(active_hash, "evidence")
            or get_phase_payload(session_id, "evidence_search")
            or get_phase_payload(session_id, "evidence")
            or {}
        )
        claims = [
            ClaimItem.model_validate(item)
            for item in (evidence_payload.get("claims") or [])
            if isinstance(item, dict)
        ]
        evidences = [
            EvidenceItem.model_validate(item)
            for item in (evidence_payload.get("evidences") or [])
            if isinstance(item, dict)
        ]

        if (not claims or not evidences) and args.record_id:
            record = get_history(args.record_id)

            if record:
                claim_reports = (record.get("report") or {}).get("claim_reports") or []
                claims = [
                    ClaimItem.model_validate((row or {}).get("claim"))
                    for row in claim_reports
                    if (row or {}).get("claim")
                ]
                evidences = [
                    EvidenceItem.model_validate(item)
                    for row in claim_reports
                    for item in ((row or {}).get("evidences") or [])
                    if isinstance(item, dict)
                ]
        if (not claims or not evidences) and preferred_text:
            yield _emit_sse_token(
                session_id,
                "检测到缺少证据中间态，正在自动补齐前置阶段（主张->证据）...\n",
            )
            claims_payload = (
                _get_hash_phase(active_hash, "claims")
                or get_phase_payload(session_id, "claims")
                or {}
            )
            claims_data = (
                claims_payload.get("claims")
                if isinstance(claims_payload, dict)
                else None
            )
            claims = [
                ClaimItem.model_validate(item)
                for item in (claims_data or [])
                if isinstance(item, dict)
            ]
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
                evidences = orchestrator.run_evidence(
                    text=preferred_text, claims=claims
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in evidences],
                    },
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

        yield _emit_sse_stage(session_id, "align_only", "running")
        with llm_slot():
            aligned = align_evidences(claims=claims, evidences=evidences)
        token_lines = []
        token_lines.append("【聚合后证据】\n\n")
        if not aligned:
            token_lines.append("未生成对齐证据。\n")
        else:
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

                        summary_text = getattr(ev, "summary", "") or getattr(
                            ev, "title", ""
                        )
                        if summary_text:
                            token_lines.append(f"[聚合后标题] {summary_text}\n")
                        else:
                            token_lines.append("[聚合后标题] （无标题）\n")

                        stance_raw = getattr(ev, "stance", "")
                        stance_zh = _zh_stance(stance_raw) if stance_raw else "证据不足"
                        token_lines.append(f"[立场] {stance_zh}\n")
                        alignment_confidence = getattr(ev, "alignment_confidence", None)
                        if alignment_confidence is not None:
                            token_lines.append(
                                f"[对齐置信度] {alignment_confidence:.2f}\n"
                            )
                        else:
                            token_lines.append("[对齐置信度] N/A\n")

                        weight = getattr(ev, "weight", None)
                        if weight is not None:
                            token_lines.append(f"[对齐权重] {weight:.2f}\n")
                        else:
                            token_lines.append("[对齐权重] N/A\n")

                        alignment_rationale = getattr(ev, "alignment_rationale", "")
                        if alignment_rationale:
                            token_lines.append(f"[对齐理由] {alignment_rationale}\n")
                        else:
                            token_lines.append("[对齐理由] （无对齐理由）\n")
                        token_lines.append("\n")

        for line in token_lines:
            yield _emit_sse_token(session_id, line)

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
            payload={
                "claims": [c.model_dump() for c in claims],
                "evidences": [e.model_dump() for e in aligned],
            },
            meta={"source": "chat", "input_text_hash": active_hash},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="evidence_align",
            payload={
                "claims": [c.model_dump() for c in claims],
                "evidences": [e.model_dump() for e in aligned],
            },
            input_text=input_text,
        )
        chat_store.update_session_meta_fields(
            session_id, {"last_phase": "evidence_align", "last_task_id": session_id}
        )

        yield _emit_sse_stage(session_id, "align_only", "done")

        summary_content = f"证据对齐完成：已输出 {len(aligned)} 条聚合后证据。"
        if not aligned:
            summary_content = "证据对齐完成：未生成有效的聚合证据。"
        msg = ChatMessage(
            role="assistant",
            content=summary_content,
            actions=[
                ChatAction(type="command", label="继续生成报告", command="/report_only")
            ]
            if aligned
            else [],
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
        claims = [
            ClaimItem.model_validate(item)
            for item in (align_payload.get("claims") or [])
            if isinstance(item, dict)
        ]
        evidences = [
            EvidenceItem.model_validate(item)
            for item in (align_payload.get("evidences") or [])
            if isinstance(item, dict)
        ]
        input_text = preferred_text or _get_hash_input_text(active_hash)
        if not input_text:
            task = load_task(session_id) or {}
            input_text = str(task.get("input_text") or "")
        if not active_hash and input_text:
            active_hash = _hash_input_text(input_text)
        if args.record_id:
            record = get_history(args.record_id)
            if record:
                report_obj = record.get("report") or {}
                claim_reports = report_obj.get("claim_reports") or []
                claims = [
                    ClaimItem.model_validate((row or {}).get("claim"))
                    for row in claim_reports
                    if (row or {}).get("claim")
                ]
                evidences = [
                    EvidenceItem.model_validate(item)
                    for row in claim_reports
                    for item in ((row or {}).get("evidences") or [])
                    if isinstance(item, dict)
                ]
                if not input_text:
                    input_text = str(record.get("input_text") or "")
        if (not claims or not evidences) and input_text:
            yield _emit_sse_token(
                session_id,
                "检测到缺少对齐中间态，正在自动补齐前置阶段（主张->证据->对齐）...\n",
            )
            claims_payload = (
                _get_hash_phase(active_hash, "claims")
                or get_phase_payload(session_id, "claims")
                or {}
            )
            claims_data = (
                claims_payload.get("claims")
                if isinstance(claims_payload, dict)
                else None
            )
            claims = [
                ClaimItem.model_validate(item)
                for item in (claims_data or [])
                if isinstance(item, dict)
            ]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(
                    session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n"
                )
                for idx, claim in enumerate(claims, start=1):
                    claim_text = getattr(claim, "text", "")
                    claim_id = getattr(claim, "claim_id", f"C{idx}")
                    yield _emit_sse_token(
                        session_id, f"{idx}. [{claim_id}] {claim_text}\n"
                    )
                yield _emit_sse_token(session_id, "\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )
            evidence_payload = (
                _get_hash_phase(active_hash, "evidence_search")
                or get_phase_payload(session_id, "evidence_search")
                or {}
            )
            evidence_data = (
                evidence_payload.get("evidences")
                if isinstance(evidence_payload, dict)
                else None
            )
            evidences = [
                EvidenceItem.model_validate(item)
                for item in (evidence_data or [])
                if isinstance(item, dict)
            ]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in evidences],
                    },
                    input_text=input_text,
                )
            if claims and evidences:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    evidences = align_evidences(claims=claims, evidences=evidences)
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据对齐结果】\n对齐证据数: {len(evidences)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in evidences],
                    },
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

        yield _emit_sse_stage(session_id, "report_only", "running")
        try:
            with llm_slot():
                report_dict = orchestrator.run_report(
                    text=input_text, claims=claims, evidences=evidences
                )
            report = ReportResponse.model_validate(report_dict)
        except Exception as e:
            logger.error("report_only 报告生成失败: %s", e)
            err_msg = ChatMessage(
                role="assistant",
                content="报告生成失败，请稍后重试或检查配置。",
                actions=[
                    ChatAction(type="command", label="重试", command="/report_only")
                ],
                references=[],
            )
            yield from _emit_and_store(err_msg)
            return
        token_lines = []
        token_lines.append("【报告详情】\n\n")

        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        scenario_zh = _SCENARIO_ZH.get(
            report.detected_scenario, report.detected_scenario
        )
        token_lines.append(f"[识别场景] {scenario_zh}\n")

        domains_zh = ", ".join([_DOMAIN_ZH.get(d, d) for d in report.evidence_domains])
        token_lines.append(f"[证据覆盖域] {domains_zh}\n")

        token_lines.append(f"[风险评分] {report.risk_score}/100\n")
        risk_level_zh = _RISK_LEVEL_ZH.get(report.risk_level, report.risk_level)
        token_lines.append(f"[风险等级] {risk_level_zh}\n")
        risk_label_zh = _RISK_LABEL_ZH.get(report.risk_label, report.risk_label)
        token_lines.append(f"[风险标签] {risk_label_zh}\n")
        token_lines.append("\n")

        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        token_lines.append("[综合摘要]\n")
        summary_text = report.summary or "（无摘要）"
        token_lines.append(f"{summary_text}\n")
        token_lines.append("\n")

        token_lines.append(f"{_CLAIM_SEPARATOR}\n")
        token_lines.append("[可疑点]\n")
        if not report.suspicious_points:
            token_lines.append("  （无明显可疑点）\n")
        else:
            for idx, point in enumerate(report.suspicious_points, start=1):
                token_lines.append(f"  {idx}. {point}\n")
        token_lines.append("\n")

        for line in token_lines:
            yield _emit_sse_token(session_id, line)

        phases = _current_phases()
        phases["report"] = "done"
        phases["simulation"] = "idle"
        phases["content"] = "idle"
        record_id = ""
        if args.persist:
            record_id = save_report(
                input_text=input_text or "[无原文]",
                report=jsonable_encoder(report),
                detect_data=None,
            )
        upsert_phase_snapshot(
            task_id=session_id,
            input_text=input_text,
            phases=phases,
            phase="report",
            status="done",
            payload={"report": report, "record_id": record_id}
            if record_id
            else {"report": report},
            meta={"source": "chat", "record_id": record_id}
            if record_id
            else {"source": "chat"},
        )
        _store_hash_phase(
            input_hash=active_hash,
            phase="report",
            payload={"report": report.model_dump(), "record_id": record_id}
            if record_id
            else {"report": report.model_dump()},
            input_text=input_text,
        )

        session_meta_update = {"last_phase": "report", "last_task_id": session_id}
        if record_id:
            session_meta_update["bound_record_id"] = record_id
        chat_store.update_session_meta_fields(session_id, session_meta_update)

        yield _emit_sse_stage(session_id, "report_only", "done")

        if args.persist and record_id:
            content_text = f"report_only 完成：已生成报告并写入历史记录 {record_id}。"
            actions = [
                ChatAction(type="command", label="仅执行舆情预演", command="/simulate"),
                ChatAction(
                    type="command", label="仅生成应对内容", command="/content_generate"
                ),
            ]
            references = [
                ChatReference(
                    title=f"历史记录：{record_id}",
                    href="/history",
                    description="可在历史记录页查看",
                )
            ]
            meta = {"phase": "report", "record_id": record_id, "task_id": session_id}
        else:
            content_text = "report_only 完成：已生成报告详情（未写入历史记录）。"
            actions = [
                ChatAction(type="command", label="仅执行舆情预演", command="/simulate"),
                ChatAction(
                    type="command", label="仅生成应对内容", command="/content_generate"
                ),
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
        report_payload = (
            _get_hash_phase(active_hash, "report")
            or get_phase_payload(session_id, "report")
            or {}
        )
        report_data = (
            report_payload.get("report") if isinstance(report_payload, dict) else None
        )
        record_id = str(
            report_payload.get("record_id")
            or args.record_id
            or session_meta.get("bound_record_id")
            or ""
        )
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
            yield _emit_sse_token(
                session_id,
                "检测到缺少报告中间态，正在自动补齐前置阶段（主张->证据->对齐->报告）...\n",
            )
            claims_payload = (
                _get_hash_phase(active_hash, "claims")
                or get_phase_payload(session_id, "claims")
                or {}
            )
            claims_data = (
                claims_payload.get("claims")
                if isinstance(claims_payload, dict)
                else None
            )
            claims = [
                ClaimItem.model_validate(item)
                for item in (claims_data or [])
                if isinstance(item, dict)
            ]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(
                    session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n"
                )
                for idx, claim in enumerate(claims, start=1):
                    claim_text = getattr(claim, "text", "")
                    claim_id = getattr(claim, "claim_id", f"C{idx}")
                    yield _emit_sse_token(
                        session_id, f"{idx}. [{claim_id}] {claim_text}\n"
                    )
                yield _emit_sse_token(session_id, "\n")
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )

            evidence_payload = (
                _get_hash_phase(active_hash, "evidence_search")
                or get_phase_payload(session_id, "evidence_search")
                or {}
            )
            evidence_data = (
                evidence_payload.get("evidences")
                if isinstance(evidence_payload, dict)
                else None
            )
            evidences = [
                EvidenceItem.model_validate(item)
                for item in (evidence_data or [])
                if isinstance(item, dict)
            ]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in evidences],
                    },
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
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据对齐结果】\n对齐证据数: {len(aligned)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in aligned],
                    },
                    input_text=input_text,
                )

            if claims and aligned:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    report_dict = orchestrator.run_report(
                        text=input_text, claims=claims, evidences=aligned
                    )
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
            cached_sim_payload = (
                _get_hash_phase(active_hash, "simulation")
                or get_phase_payload(session_id, "simulation")
                or {}
            )
            cached_sim_data = (
                cached_sim_payload.get("simulation")
                if isinstance(cached_sim_payload, dict)
                else None
            )
            if isinstance(cached_sim_data, dict):
                sim = SimulateResponse.model_validate(cached_sim_data)
                yield _emit_sse_stage(session_id, "simulate", "running")
                yield _emit_sse_token(
                    session_id,
                    "命中会话缓存：复用最近一次舆情预演结果（未重复调用模型）。\n",
                )
                yield _emit_sse_token(
                    session_id,
                    f"【舆情预演-情绪分布】\n情绪项: {len(sim.emotion_distribution)}，立场项: {len(sim.stance_distribution)}\n\n",
                )
                yield _emit_sse_token(
                    session_id,
                    f"【舆情预演-叙事分支】\n分支数: {len(sim.narratives)}\n\n",
                )
                yield _emit_sse_token(
                    session_id,
                    f"【舆情预演-引爆点】\n条目数: {len(sim.flashpoints)}\n\n",
                )
                yield _emit_sse_token(
                    session_id,
                    f"【舆情预演-时间线】\n条目数: {len(sim.timeline or [])}\n\n",
                )
                action_count = (
                    len((sim.suggestion or {}).actions or []) if sim.suggestion else 0
                )
                yield _emit_sse_token(
                    session_id, f"【舆情预演-应对建议】\n行动项: {action_count}\n\n"
                )
                yield _emit_sse_stage(session_id, "simulate", "done")
                msg = ChatMessage(
                    role="assistant",
                    content="simulate 完成：命中会话缓存，已返回最近结果。",
                    actions=[
                        ChatAction(
                            type="command",
                            label="继续生成应对内容",
                            command="/content_generate",
                        )
                    ],
                    references=[],
                    meta={
                        "phase": "simulation",
                        "record_id": record_id,
                        "task_id": session_id,
                        "cache_hit": True,
                    },
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
                accumulated["emotion_drivers"] = [
                    str(x) for x in emotion_drivers if str(x).strip()
                ]
                accumulated["stance_drivers"] = [
                    str(x) for x in stance_drivers if str(x).strip()
                ]

                token_lines.append("【舆情预演-情绪分布】\n")
                for k, v in (
                    emotion_distribution.items()
                    if isinstance(emotion_distribution, dict)
                    else []
                ):
                    try:
                        token_lines.append(f"[情绪] {k}: {float(v) * 100:.0f}%\n")
                    except Exception:
                        token_lines.append(f"[情绪] {k}: {v}\n")
                for k, v in (
                    stance_distribution.items()
                    if isinstance(stance_distribution, dict)
                    else []
                ):
                    try:
                        token_lines.append(f"[立场] {k}: {float(v) * 100:.0f}%\n")
                    except Exception:
                        token_lines.append(f"[立场] {k}: {v}\n")
                if accumulated["emotion_drivers"]:
                    token_lines.append(
                        f"[情绪驱动] {'；'.join(accumulated['emotion_drivers'][:3])}\n"
                    )
                if accumulated["stance_drivers"]:
                    token_lines.append(
                        f"[立场驱动] {'；'.join(accumulated['stance_drivers'][:3])}\n"
                    )
                token_lines.append("\n")

            elif stage == "narratives":
                narratives_data = data.get("narratives") or []
                accumulated["narratives"] = (
                    narratives_data if isinstance(narratives_data, list) else []
                )

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

                    token_lines.append(
                        f"{idx}. {title}（立场: {stance}，概率: {prob_text}）\n"
                    )
                    if isinstance(keywords, list) and keywords:
                        token_lines.append(
                            f"   - 触发关键词: {'、'.join([str(k) for k in keywords[:5]])}\n"
                        )
                    if sample_message:
                        token_lines.append(f"   - 示例: {sample_message}\n")
                token_lines.append("\n")

            elif stage == "flashpoints":
                flashpoints = data.get("flashpoints") or []
                timeline = data.get("timeline") or []
                accumulated["flashpoints"] = (
                    [str(x) for x in flashpoints if str(x).strip()]
                    if isinstance(flashpoints, list)
                    else []
                )
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
                        token_lines.append(
                            f"[T+{hour}h] {event}（预计触达: {expected_reach}）\n"
                        )
                token_lines.append("\n")

            elif stage == "suggestion":
                suggestion_data = data.get("suggestion") or {}
                accumulated["suggestion"] = (
                    suggestion_data
                    if isinstance(suggestion_data, dict)
                    else {"summary": "", "actions": []}
                )

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
                    token_lines.append(
                        f"{idx}. [{priority}/{category}] {action_text}\n"
                    )
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
            {
                "last_phase": "simulation",
                "last_task_id": session_id,
                "bound_record_id": record_id,
            },
        )
        _save_session_cache_entry(session_id, "session_cache_simulate", sim_cache_key)
        yield _emit_sse_stage(session_id, "simulate", "done")
        msg = ChatMessage(
            role="assistant",
            content="simulate 完成：已生成舆情预演结果。",
            actions=[
                ChatAction(
                    type="command",
                    label="继续生成应对内容",
                    command="/content_generate",
                )
            ],
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

        def _render_content_lines(
            content_resp: ContentGenerateResponse, detail_mode: str
        ) -> list[str]:
            lines: list[str] = []
            faq_items = content_resp.faq or []
            scripts = content_resp.platform_scripts or []
            lines.append("【应对内容生成结果】\n")
            lines.append("[澄清稿] 3 个版本（短/中/长）\n")
            lines.append(f"[FAQ] {len(faq_items)} 条\n")
            lines.append(f"[平台话术] {len(scripts)} 条\n\n")
            if detail_mode == "brief":
                lines.extend(
                    _content_block(
                        "clarification_short_preview",
                        (content_resp.clarification.short or "")[:300],
                    )
                )
                if faq_items:
                    lines.extend(
                        _content_block(
                            "faq_preview",
                            f"Q: {faq_items[0].question}\nA: {faq_items[0].answer}",
                        )
                    )
                if scripts:
                    lines.extend(
                        _content_block(
                            "script_preview",
                            f"[{scripts[0].platform}]\n{scripts[0].content}",
                        )
                    )
                return lines

            lines.extend(
                _content_block(
                    "clarification_short", content_resp.clarification.short or ""
                )
            )
            lines.extend(
                _content_block(
                    "clarification_medium", content_resp.clarification.medium or ""
                )
            )
            lines.extend(
                _content_block(
                    "clarification_long", content_resp.clarification.long or ""
                )
            )
            for idx, item in enumerate(faq_items, start=1):
                lines.extend(
                    _content_block(
                        f"faq_{idx}", f"Q: {item.question}\nA: {item.answer}"
                    )
                )
            for script in scripts:
                lines.extend(
                    _content_block(f"script_{script.platform}", script.content)
                )
            return lines

        active_hash = str(session_meta.get("input_text_hash") or "")
        preferred_text = str(args.text or "").strip()
        if preferred_text:
            active_hash = _hash_input_text(preferred_text)
        report_payload = _get_hash_phase(active_hash, "report") or (
            {} if preferred_text else (get_phase_payload(session_id, "report") or {})
        )
        simulation_payload = _get_hash_phase(active_hash, "simulation") or (
            {}
            if preferred_text
            else (get_phase_payload(session_id, "simulation") or {})
        )
        report_data = (
            report_payload.get("report") if isinstance(report_payload, dict) else None
        )
        simulation_data = (
            simulation_payload.get("simulation")
            if isinstance(simulation_payload, dict)
            else None
        )
        record_id = str(
            report_payload.get("record_id")
            or args.record_id
            or session_meta.get("bound_record_id")
            or ""
        )
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
        existing_content_data = (
            existing_content_payload.get("content")
            if isinstance(existing_content_payload, dict)
            else None
        )

        if operation == "show":
            if isinstance(existing_content_data, dict):
                content_resp_show = ContentGenerateResponse.model_validate(
                    existing_content_data
                )
                yield _emit_sse_stage(session_id, "content_generate", "running")
                yield _emit_sse_token(
                    session_id, "已加载当前会话中已生成的应对内容。\n"
                )
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
                    custom_lines.extend(
                        _content_block(f"clarification_{variant or 'short'}", chosen)
                    )
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
                        custom_lines.extend(
                            _content_block(
                                f"faq_{idx}", f"Q: {item.question}\nA: {item.answer}"
                            )
                        )
                    if not custom_lines:
                        custom_lines.extend(_content_block("faq", "未匹配到 FAQ 条目"))
                elif section == "scripts":
                    wanted = (
                        {x.strip() for x in platforms.split(",") if x.strip()}
                        if platforms
                        else set()
                    )
                    scripts = content_resp_show.platform_scripts or []
                    for script in scripts:
                        platform_name = str(script.platform)
                        if wanted and platform_name not in wanted:
                            continue
                        custom_lines.extend(
                            _content_block(f"script_{platform_name}", script.content)
                        )
                    if not custom_lines:
                        custom_lines.extend(
                            _content_block("scripts", "未匹配到平台话术")
                        )

                lines_to_emit = custom_lines or _render_content_lines(
                    content_resp_show, detail
                )
                for line in lines_to_emit:
                    yield _emit_sse_token(session_id, line)
                yield _emit_sse_stage(session_id, "content_generate", "done")
                show_msg = ChatMessage(
                    role="assistant",
                    content="content_show 完成：已展示已生成内容。",
                    actions=[
                        ChatAction(
                            type="command",
                            label="完整查看",
                            command="/content detail=full",
                        )
                    ],
                    references=[],
                    meta={
                        "phase": "content",
                        "record_id": record_id,
                        "task_id": session_id,
                        "cache_hit": True,
                    },
                )
                yield from _emit_and_store(show_msg)
                return

            no_show_msg = ChatMessage(
                role="assistant",
                content="当前会话暂无可展示的应对内容。请先执行 /content 或 /content_generate 生成。",
                actions=[
                    ChatAction(type="command", label="立即生成", command="/content")
                ],
                references=[],
            )
            yield from _emit_and_store(no_show_msg)
            return

        if (
            (not args.force)
            and isinstance(existing_content_data, dict)
            and not isinstance(report_data, dict)
        ):
            content_resp_fallback = ContentGenerateResponse.model_validate(
                existing_content_data
            )
            yield _emit_sse_stage(session_id, "content_generate", "running")
            yield _emit_sse_token(
                session_id, "报告中间态缺失，已直接复用当前会话已有应对内容。\n"
            )
            for line in _render_content_lines(content_resp_fallback, detail):
                yield _emit_sse_token(session_id, line)
            yield _emit_sse_stage(session_id, "content_generate", "done")
            fallback_msg = ChatMessage(
                role="assistant",
                content="content_generate 完成：已复用已有内容（未重复生成）。",
                actions=[
                    ChatAction(
                        type="command",
                        label="强制重生成",
                        command="/content force=true",
                    )
                ],
                references=[],
                meta={
                    "phase": "content",
                    "record_id": record_id,
                    "task_id": session_id,
                    "cache_hit": True,
                },
            )
            yield from _emit_and_store(fallback_msg)
            return

        if args.reuse_only and not isinstance(existing_content_data, dict):
            reuse_only_msg = ChatMessage(
                role="assistant",
                content="reuse_only=true：当前未命中可复用内容，已跳过生成。可使用 /content force=true 触发重生成。",
                actions=[
                    ChatAction(
                        type="command",
                        label="强制重生成",
                        command="/content force=true",
                    )
                ],
                references=[],
            )
            yield from _emit_and_store(reuse_only_msg)
            return

        if not isinstance(report_data, dict) and input_text:
            yield _emit_sse_token(
                session_id,
                "检测到缺少报告中间态，正在自动补齐前置阶段（主张->证据->对齐->报告）...\n",
            )
            claims_payload = _get_hash_phase(active_hash, "claims") or {}
            claims_data = (
                claims_payload.get("claims")
                if isinstance(claims_payload, dict)
                else None
            )
            claims = [
                ClaimItem.model_validate(item)
                for item in (claims_data or [])
                if isinstance(item, dict)
            ]
            if not claims:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    claims = orchestrator.run_claims(input_text)
                yield _emit_sse_token(
                    session_id, f"【自动补齐-主张抽取结果】\n主张数: {len(claims)}\n\n"
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="claims",
                    payload={"claims": [c.model_dump() for c in claims]},
                    input_text=input_text,
                )

            evidence_payload = _get_hash_phase(active_hash, "evidence_search") or {}
            evidence_data = (
                evidence_payload.get("evidences")
                if isinstance(evidence_payload, dict)
                else None
            )
            evidences = [
                EvidenceItem.model_validate(item)
                for item in (evidence_data or [])
                if isinstance(item, dict)
            ]
            if not evidences and claims:
                evidences = orchestrator.run_evidence(text=input_text, claims=claims)
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据检索结果】\n证据数: {len(evidences)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_search",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in evidences],
                    },
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
                yield _emit_sse_token(
                    session_id,
                    f"【自动补齐-证据对齐结果】\n对齐证据数: {len(aligned)}\n\n",
                )
                _store_hash_phase(
                    input_hash=active_hash,
                    phase="evidence_align",
                    payload={
                        "claims": [c.model_dump() for c in claims],
                        "evidences": [e.model_dump() for e in aligned],
                    },
                    input_text=input_text,
                )

            if claims and aligned:
                llm_budget_msg = _check_and_bump_llm_budget()
                if llm_budget_msg is not None:
                    yield from _emit_and_store(llm_budget_msg)
                    return
                with llm_slot():
                    report_dict = orchestrator.run_report(
                        text=input_text, claims=claims, evidences=aligned
                    )
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
            existing_content_key = str(
                existing_content_payload.get("content_key") or ""
            )
        can_reuse_existing = isinstance(existing_content_data, dict) and (
            existing_content_key == content_cache_key or not existing_content_key
        )

        if (not args.force) and can_reuse_existing:
            content_resp_existing = ContentGenerateResponse.model_validate(
                existing_content_data
            )
            yield _emit_sse_stage(session_id, "content_generate", "running")
            yield _emit_sse_token(
                session_id, "命中已生成内容：复用会话中的应对内容（未重复调用模型）。\n"
            )
            for line in _render_content_lines(content_resp_existing, detail):
                yield _emit_sse_token(session_id, line)
            yield _emit_sse_stage(session_id, "content_generate", "done")
            msg_existing = ChatMessage(
                role="assistant",
                content="content_generate 完成：已复用当前会话内容。",
                actions=[
                    ChatAction(
                        type="command",
                        label="强制重生成",
                        command="/content force=true",
                    ),
                    ChatAction(
                        type="command",
                        label="按模块查看",
                        command="/content_show clarification short",
                    ),
                ],
                references=[],
                meta={
                    "phase": "content",
                    "record_id": record_id,
                    "task_id": session_id,
                    "cache_hit": True,
                },
            )
            yield from _emit_and_store(msg_existing)
            return

        if args.reuse_only and not can_reuse_existing:
            reuse_only_msg = ChatMessage(
                role="assistant",
                content="reuse_only=true：当前未命中可复用内容，已跳过生成。可使用 /content force=true 触发重生成。",
                actions=[
                    ChatAction(
                        type="command",
                        label="强制重生成",
                        command="/content force=true",
                    )
                ],
                references=[],
            )
            yield from _emit_and_store(reuse_only_msg)
            return

        if bool(session_meta.get("content_generation_in_progress")) and not args.force:
            in_progress_msg = ChatMessage(
                role="assistant",
                content="当前已有应对内容生成任务进行中，请稍后使用 /content 查看结果，避免重复生成。",
                actions=[
                    ChatAction(type="command", label="查看当前内容", command="/content")
                ],
                references=[],
            )
            yield from _emit_and_store(in_progress_msg)
            return

        content_cache_entry = session_meta.get("session_cache_content_generate")
        if (not args.force) and _is_cache_hit(content_cache_entry, content_cache_key):
            cached_content_payload = _get_hash_phase(active_hash, "content") or {}
            cached_content_data = (
                cached_content_payload.get("content")
                if isinstance(cached_content_payload, dict)
                else None
            )
            if isinstance(cached_content_data, dict):
                content_resp = ContentGenerateResponse.model_validate(
                    cached_content_data
                )
                yield _emit_sse_stage(session_id, "content_generate", "running")
                yield _emit_sse_token(
                    session_id,
                    "命中会话缓存：复用最近一次应对内容结果（未重复调用模型）。\n",
                )
                for line in _render_content_lines(content_resp, detail):
                    yield _emit_sse_token(session_id, line)
                yield _emit_sse_stage(session_id, "content_generate", "done")
                msg = ChatMessage(
                    role="assistant",
                    content="content_generate 完成：命中会话缓存，已返回最近结果。",
                    actions=[
                        ChatAction(
                            type="command",
                            label="查看完整内容",
                            command="/content detail=full",
                        ),
                        ChatAction(type="link", label="打开应对内容", href="/content"),
                    ],
                    references=[],
                    meta={
                        "phase": "content",
                        "record_id": record_id,
                        "task_id": session_id,
                        "cache_hit": True,
                    },
                )
                yield from _emit_and_store(msg)
                return

        llm_budget_msg = _check_and_bump_llm_budget()
        if llm_budget_msg is not None:
            yield from _emit_and_store(llm_budget_msg)
            return

        yield _emit_sse_stage(session_id, "content_generate", "running")
        yield _emit_sse_token(
            session_id, "正在生成应对内容（澄清稿 / FAQ / 多平台话术）...\n"
        )
        chat_store.update_session_meta_fields(
            session_id, {"content_generation_in_progress": True}
        )
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
            logger.error("content_generate 失败: %s", e)
            chat_store.update_session_meta_fields(
                session_id, {"content_generation_in_progress": False}
            )
            session_meta["content_generation_in_progress"] = False
            err_msg = ChatMessage(
                role="assistant",
                content="应对内容生成失败，请稍后重试。",
                actions=[
                    ChatAction(
                        type="command", label="重试", command="/content_generate"
                    )
                ],
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
        chat_store.update_session_meta_fields(
            session_id, {"content_generation_in_progress": False}
        )
        session_meta["content_generation_in_progress"] = False
        chat_store.update_session_meta_fields(
            session_id,
            {
                "last_phase": "content",
                "last_task_id": session_id,
                "bound_record_id": record_id,
            },
        )
        _save_session_cache_entry(
            session_id, "session_cache_content_generate", content_cache_key
        )
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
                ChatAction(
                    type="command", label="查看完整内容", command="/content detail=full"
                ),
                ChatAction(
                    type="command",
                    label="按模块查看",
                    command="/content_show clarification short",
                ),
                ChatAction(type="link", label="打开应对内容", href="/content"),
            ],
            references=[],
            meta={"phase": "content", "record_id": record_id, "task_id": session_id},
        )
        yield from _emit_and_store(msg)
        return
