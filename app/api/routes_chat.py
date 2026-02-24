import time
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.core.concurrency import llm_slot
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

router = APIRouter(prefix="/chat", tags=["chat"])


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
    if t.startswith("/analyze "):
        return True
    # 粗略启发：超长输入大概率是待分析文本
    return len(t) >= 180


def _extract_analyze_text(text: str) -> str:
    t = text.strip()
    if t.startswith("/analyze "):
        return t[len("/analyze ") :].strip()
    return t


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
        msg = ChatMessage(
            role="assistant",
            content=(
                "目前 /chat 已支持最小工具白名单编排的第一步。\n\n"
                "- 若要发起分析：发送 `/analyze <待分析文本>`（建议粘贴完整原文）\n"
                "- 若只是问答：请在问题里附上原文或给出 record_id（后续会接入 history 绑定）\n\n"
                f"你输入的是：{text[:200]}"
            ),
            actions=base_actions
            + [
                ChatAction(type="command", label="示例：开始分析", command="/analyze 网传某事件100%真实，内部人士称..."),
            ],
            references=[],
        )
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

            if tool == "help":
                msg = build_help_message()
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if tool == "load_history":
                args = ToolLoadHistoryArgs.model_validate(args_dict)
                msg = run_load_history(args)
                if msg.meta and msg.meta.get("record_id"):
                    try:
                        chat_store.update_session_meta(session_id, "bound_record_id", msg.meta["record_id"])
                    except Exception:
                        pass
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if tool == "list":
                args = ToolListArgs.model_validate(args_dict)
                msg = run_list(args)
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if tool == "why":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolWhyArgs.model_validate(args_dict)
                    msg = run_why(args)
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if tool == "more_evidence":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolMoreEvidenceArgs.model_validate(args_dict)
                    msg = run_more_evidence(args)
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            if tool == "rewrite":
                try:
                    if not (args_dict.get("record_id") or "").strip():
                        args_dict["record_id"] = str(ctx.get("record_id") or ctx.get("recordId") or "")
                    args = ToolRewriteArgs.model_validate(args_dict)
                    msg = run_rewrite(args)
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
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
                        meta=msg.meta,
                    )
                except Exception:
                    pass
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
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
                event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
                yield f"data: {event.model_dump_json()}\n\n"
                yield f"data: {ChatStreamEvent(type='done', data={'session_id': session_id}).model_dump_json()}\n\n"
                return

            # 0.1) /list [N] 或 /history 或 /records
            if text.startswith("/list") or text.startswith("/history") or text.startswith("/records"):
                tool, args_dict = parse_tool(text)
                if tool != "list":
                    msg = build_help_message()
                else:
                    msg = run_list(ToolListArgs.model_validate(args_dict))
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
                        meta=getattr(msg, "meta", None) or {},
                    )
                except Exception:
                    pass
                return

            # 0) 非分析意图：直接返回结构化 message（仍走 SSE 通道）
            if not _is_analyze_intent(text):
                msg = ChatMessage(
                    role="assistant",
                    content=(
                        "目前 /chat/stream 已对齐 /chat 的最小工具白名单编排。\n\n"
                        "- 若要发起分析：发送 `/analyze <待分析文本>`（建议粘贴完整原文）\n"
                        "- 若只是问答：请在问题里附上原文或给出 record_id（后续会接入 history 绑定）\n\n"
                        f"你输入的是：{text[:200]}"
                    ),
                    actions=base_actions
                    + [
                        ChatAction(
                            type="command",
                            label="示例：开始分析",
                            command="/analyze 网传某事件100%真实，内部人士称...",
                        ),
                    ],
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

