from typing import Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.concurrency import llm_slot
from app.core.guardrails import build_guardrails_warning_message, validate_tool_call
from app.core.logger import get_logger
from app.orchestrator import orchestrator
from app.schemas.chat import (
    ChatAction,
    ChatMessage,
    ChatMessageCreateRequest,
    ChatReference,
    ChatStreamEvent,
)
from app.services import chat_store
from app.services.chat_orchestrator import (
    ToolAnalyzeArgs,
    ToolCompareArgs,
    ToolDeepDiveArgs,
    ToolListArgs,
    ToolLoadHistoryArgs,
    ToolMoreEvidenceArgs,
    ToolRewriteArgs,
    ToolWhyArgs,
    build_help_message,
    build_intent_clarify_message,
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
from app.services.history_store import save_report
from app.services.pipeline import align_evidences
from app.services.pipeline_state_store import upsert_phase_snapshot
from app.services.risk_snapshot import detect_risk_snapshot

from .formatters import (
    _CLAIM_SEPARATOR,
    _EVIDENCE_SEPARATOR,
    _truncate_text,
    _zh_domain,
    _zh_risk_label,
    _zh_risk_level,
    _zh_scenario,
    _zh_stance,
)
from .skill_handlers import _handle_single_skill_tool
from .sse_helpers import _emit_sse_done, _emit_sse_message, _safe_append_message

router = APIRouter()
logger = get_logger(__name__)


@router.post("/sessions/{session_id}/messages/stream")
def chat_session_stream(
    session_id: str, payload: ChatMessageCreateRequest
) -> StreamingResponse:
    """V2 会话化 SSE：追加用户消息 -> 工具白名单编排 -> 逐步输出 -> 写入 assistant 消息。"""

    sess = chat_store.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session_not_found")

    text = payload.text.strip()

    try:
        chat_store.append_message(
            session_id, role="user", content=text, meta={"context": payload.context}
        )
    except Exception:
        pass

    def event_generator() -> Iterator[str]:
        try:
            session_meta = chat_store.get_session_meta(session_id)
            tool, args_dict = parse_tool(text, session_meta=session_meta)
            ctx = payload.context or {}

            if tool in {
                "claims_only",
                "evidence_only",
                "align_only",
                "report_only",
                "simulate",
                "content_generate",
            }:
                for line in _handle_single_skill_tool(
                    session_id=session_id,
                    tool=tool,
                    args_dict=args_dict,
                    session_meta=session_meta,
                ):
                    yield line
                return

            if tool == "help":
                if bool(args_dict.get("clarify")):
                    msg = build_intent_clarify_message(
                        str(args_dict.get("text") or text)
                    )
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
                        chat_store.update_session_meta(
                            session_id, "bound_record_id", msg.meta["record_id"]
                        )
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
                        args_dict["record_id"] = str(
                            ctx.get("record_id") or ctx.get("recordId") or ""
                        )
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
                        args_dict["record_id"] = str(
                            ctx.get("record_id") or ctx.get("recordId") or ""
                        )
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
                        args_dict["record_id"] = str(
                            ctx.get("record_id") or ctx.get("recordId") or ""
                        )
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
                        actions=[
                            ChatAction(
                                type="command", label="列出最近记录", command="/list"
                            )
                        ],
                        references=[],
                    )
                _safe_append_message(session_id, msg)
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

            if tool == "deep_dive":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(
                            ctx.get("record_id") or ctx.get("recordId") or ""
                        )
                    args = ToolDeepDiveArgs.model_validate(args_dict)
                    msg = run_deep_dive(args)
                except ValidationError:
                    msg = ChatMessage(
                        role="assistant",
                        content="用法：/deep_dive <record_id> [focus] [claim_index]\n\n"
                        "- focus 可选：general（默认）/evidence/claims/timeline/sources\n"
                        "- claim_index：指定深入分析第几条主张（从0开始）\n\n"
                        "例如：/deep_dive rec_abc123 evidence",
                        actions=[
                            ChatAction(
                                type="command", label="列出最近记录", command="/list"
                            )
                        ],
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
                    content=f"参数校验失败：\n- "
                    + "\n- ".join(validation.errors)
                    + "\n\n请检查输入后重试。",
                    actions=[
                        ChatAction(type="command", label="查看帮助", command="/help")
                    ],
                    references=[],
                )
                event = ChatStreamEvent(
                    type="message",
                    data={"session_id": session_id, "message": msg.model_dump()},
                )
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if validation.warnings:
                warning_prefix = build_guardrails_warning_message(validation.warnings)
                yield f"data: {ChatStreamEvent(type='token', data={'content': warning_prefix, 'session_id': session_id}).model_dump_json()}\n\n"

            args_dict = validation.args

            args = ToolAnalyzeArgs.model_validate(args_dict)
            analyze_text = args.text

            phases_state: dict[str, str] = {
                "detect": "idle",
                "claims": "idle",
                "evidence": "idle",
                "report": "idle",
                "simulation": "idle",
                "content": "idle",
            }

            yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'risk', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 风险初判：计算中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
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
                risk = detect_risk_snapshot(
                    analyze_text, force=args.force, enable_news_gate=True
                )
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险初判：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'risk', 'status': 'done'}).model_dump_json()}\n\n"
            risk_reasons = [
                str(item) for item in (risk.reasons or []) if str(item).strip()
            ]
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
                risk_detail_lines.append(
                    f"[风险详情] 风险策略: {_truncate_text(strategy.risk_reason, 72)}"
                )
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
                claim_id = str(
                    getattr(claim, "claim_id", f"c{idx}") or f"c{idx}"
                ).upper()
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
            evidences = orchestrator.run_evidence(
                text=analyze_text, claims=claims, strategy=risk.strategy
            )
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_search', 'status': 'done'}).model_dump_json()}\n\n"
            evidence_lines = ["【原始检索证据】"]
            for idx, claim in enumerate(claims, start=1):
                if idx > 1:
                    evidence_lines.append(_CLAIM_SEPARATOR)
                claim_id = str(
                    getattr(claim, "claim_id", f"c{idx}") or f"c{idx}"
                ).upper()
                claim_text = str(getattr(claim, "claim_text", "") or "").strip()
                evidence_lines.append(f"[主张 {claim_id}] {claim_text}")

                related = [
                    ev
                    for ev in evidences
                    if str(getattr(ev, "claim_id", ""))
                    == str(getattr(claim, "claim_id", ""))
                ]
                if not related:
                    evidence_lines.append("  [证据] 无")
                    continue

                for evidence_idx, ev in enumerate(related, start=1):
                    title = str(
                        getattr(ev, "title", "") or getattr(ev, "summary", "") or "无"
                    ).strip()
                    link = str(getattr(ev, "url", "") or "无")
                    summary = _truncate_text(
                        getattr(ev, "summary", "")
                        or getattr(ev, "raw_snippet", "")
                        or "无",
                        120,
                    )
                    evidence_lines.append(f"  [证据 {evidence_idx}]")
                    evidence_lines.append(f"    [标题] {title}")
                    evidence_lines.append(f"    [来源链接] {link}")
                    evidence_lines.append(f"    [摘要] {summary}")
                    if evidence_idx < len(related):
                        evidence_lines.append(f"    {_EVIDENCE_SEPARATOR}")
            yield f"data: {ChatStreamEvent(type='token', data={'content': '\n'.join(evidence_lines) + '\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_align', 'status': 'running'}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 证据聚合与对齐：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                aligned = align_evidences(
                    claims=claims, evidences=evidences, strategy=risk.strategy
                )
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='stage', data={'session_id': session_id, 'stage': 'evidence_align', 'status': 'done'}).model_dump_json()}\n\n"
            align_lines = ["【聚合后证据】"]
            for idx, claim in enumerate(claims, start=1):
                if idx > 1:
                    align_lines.append(_CLAIM_SEPARATOR)
                claim_id = str(
                    getattr(claim, "claim_id", f"c{idx}") or f"c{idx}"
                ).upper()
                claim_text = str(getattr(claim, "claim_text", "") or "").strip()
                align_lines.append(f"[主张 {claim_id}] {claim_text}")

                related = [
                    ev
                    for ev in aligned
                    if str(getattr(ev, "claim_id", ""))
                    == str(getattr(claim, "claim_id", ""))
                ]
                if not related:
                    align_lines.append("  [聚合证据] 无")
                    continue

                for evidence_idx, ev in enumerate(related, start=1):
                    merged_title = str(
                        getattr(ev, "summary", "")
                        if getattr(ev, "source_type", "") == "web_summary"
                        else getattr(ev, "title", "")
                    ).strip()
                    stance_text = _zh_stance(getattr(ev, "stance", ""))
                    conf = getattr(ev, "alignment_confidence", None)
                    conf_text = (
                        f"{float(conf):.2f}" if isinstance(conf, (int, float)) else "无"
                    )
                    weight = getattr(ev, "source_weight", None)
                    weight_text = (
                        f"{float(weight):.2f}"
                        if isinstance(weight, (int, float))
                        else "无"
                    )
                    rationale = _truncate_text(
                        getattr(ev, "alignment_rationale", "") or "无", 120
                    )

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
            suspicious_points = [
                str(item)
                for item in (report.get("suspicious_points") or [])
                if str(item).strip()
            ]
            evidence_domains = [
                str(item)
                for item in (report.get("evidence_domains") or [])
                if str(item).strip()
            ]
            scenario_zh = _zh_scenario(report.get("detected_scenario"))
            evidence_domains_zh = [
                d for d in (_zh_domain(item) for item in evidence_domains) if d
            ]
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
                    f"- 风险初判: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
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
                    ChatAction(
                        type="command",
                        label="加载本次结果到前端",
                        command=f"/load_history {record_id}",
                    ),
                    ChatAction(
                        type="command",
                        label="为什么这样判定",
                        command=f"/why {record_id}",
                    ),
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

            event = ChatStreamEvent(
                type="message",
                data={"session_id": session_id, "message": msg.model_dump()},
            )
            yield f"data: {event.model_dump_json()}\n\n"
            yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
        except Exception as e:
            logger.error("chat_session_stream 异常: %s", e)
            err = ChatStreamEvent(
                type="error",
                data={
                    "session_id": session_id,
                    "message": "处理请求时发生内部错误，请稍后重试",
                },
            )
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
