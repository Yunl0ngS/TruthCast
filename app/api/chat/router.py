from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from app.core.concurrency import llm_slot
from app.orchestrator import orchestrator
from app.schemas.chat import (
    ChatAction,
    ChatMessage,
    ChatReference,
    ChatRequest,
    ChatResponse,
    ChatSession,
    ChatSessionCreateRequest,
    ChatSessionDetailResponse,
    ChatSessionListResponse,
)
from app.services import chat_store
from app.services.chat_orchestrator import (
    ToolListArgs,
    ToolMoreEvidenceArgs,
    ToolRewriteArgs,
    ToolWhyArgs,
    build_help_message,
    build_intent_clarify_message,
    build_why_usage_message,
    parse_tool,
    run_list,
    run_more_evidence,
    run_rewrite,
    run_why,
)
from app.services.history_store import save_report
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot

from .formatters import _zh_risk_label, _zh_scenario
from .session_helpers import _ensure_session, _extract_analyze_text, _is_analyze_intent
from .skill_handlers import _handle_single_skill_tool
from .stream_v1 import router as stream_v1_router
from .stream_v2 import router as stream_v2_router

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    """对话编排端点（V1：工具白名单编排的第一步，先非流式）。"""

    session_id = _ensure_session(payload.session_id)
    text = payload.text.strip()

    try:
        chat_store.append_message(session_id, role="user", content=text)
    except Exception:
        pass

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="公关响应", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

    if text.startswith("/why") or text.startswith("/explain"):
        parts = text.split()
        record_id = parts[1] if len(parts) >= 2 else ""
        if not record_id and payload.context:
            record_id = str(
                payload.context.get("record_id")
                or payload.context.get("recordId")
                or ""
            )
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

    if text.startswith("/more_evidence") or text.startswith("/more"):
        record_id = ""
        if payload.context:
            record_id = str(
                payload.context.get("record_id")
                or payload.context.get("recordId")
                or ""
            )
        try:
            msg = run_more_evidence(
                ToolMoreEvidenceArgs.model_validate({"record_id": record_id})
            )
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

    if text.startswith("/rewrite"):
        parts = text.split()
        style = parts[1] if len(parts) >= 2 else "short"
        record_id = ""
        if payload.context:
            record_id = str(
                payload.context.get("record_id")
                or payload.context.get("recordId")
                or ""
            )
        try:
            msg = run_rewrite(
                ToolRewriteArgs.model_validate({"record_id": record_id, "style": style})
            )
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

    if (
        text.startswith("/list")
        or text.startswith("/history")
        or text.startswith("/records")
    ):
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

    with llm_slot():
        risk = detect_risk_snapshot(analyze_text, enable_news_gate=True)

    with llm_slot():
        claims = orchestrator.run_claims(analyze_text, strategy=risk.strategy)

    evidences = orchestrator.run_evidence(
        text=analyze_text, claims=claims, strategy=risk.strategy
    )

    with llm_slot():
        aligned = align_evidences(
            claims=claims, evidences=evidences, strategy=risk.strategy
        )

    with llm_slot():
        report = orchestrator.run_report(
            text=analyze_text, claims=claims, evidences=aligned, strategy=risk.strategy
        )

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
        f"- 风险初判: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
        f"- 主张数: {len(claims)}\n"
        f"- 对齐证据数: {len(aligned)}\n"
        f"- 报告风险: {_zh_risk_label(report.get('risk_label'))}（{report.get('risk_score')}）\n"
        f"- 场景: {_zh_scenario(report.get('detected_scenario'))}\n\n"
        "提示：下一步将对接对话工作台的‘加载该 record_id 到上下文’以实现真正追问与迭代。"
    )

    analyze_actions = base_actions + [
        ChatAction(
            type="command",
            label="加载本次结果到前端",
            command=f"/load_history {record_id}",
        ),
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
def get_chat_session_detail(
    session_id: str, limit: int = 50
) -> ChatSessionDetailResponse:
    sess = chat_store.get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    messages = chat_store.list_messages(session_id, limit=limit)
    return ChatSessionDetailResponse(
        session=ChatSession(**sess),
        messages=[ChatMessage(**m) for m in messages],
    )


router.include_router(stream_v2_router)
router.include_router(stream_v1_router)
