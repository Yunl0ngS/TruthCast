from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.concurrency import llm_slot
from app.core.logger import get_logger
from app.orchestrator import orchestrator
from app.schemas.chat import (
    ChatAction,
    ChatMessage,
    ChatReference,
    ChatRequest,
    ChatStreamEvent,
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
from pydantic import ValidationError

from .formatters import _zh_risk_label, _zh_scenario
from .session_helpers import _ensure_session, _extract_analyze_text, _is_analyze_intent
from .sse_helpers import _emit_sse_done, _emit_sse_message, _safe_append_message

router = APIRouter()
logger = get_logger(__name__)


@router.post("/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """SSE 流式对话（V1：对齐 /chat 的最小工具编排，逐步输出 token + 最终结构化 message）。
    **DEPRECATED**: 建议使用 POST /chat/sessions/{session_id}/messages/stream (V2)
    事件格式：data: {"type":..., "data":...}\n\n
    """

    session_id = _ensure_session(payload.session_id)
    text = payload.text.strip()

    try:
        chat_store.append_message(
            session_id, role="user", content=text, meta={"context": payload.context}
        )
    except Exception:
        pass

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="公关响应", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

    def event_generator() -> Iterator[str]:
        try:
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
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                _safe_append_message(session_id, msg)
                return

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
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

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
                        ToolRewriteArgs.model_validate(
                            {"record_id": record_id, "style": style}
                        )
                    )
                except ValidationError:
                    msg = build_why_usage_message()
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                return

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
                yield _emit_sse_message(session_id, msg)
                yield _emit_sse_done(session_id)
                _safe_append_message(session_id, msg)
                return

            if not _is_analyze_intent(text):
                msg = build_intent_clarify_message(text)
                event = ChatStreamEvent(
                    type="message",
                    data={"session_id": session_id, "message": msg.model_dump()},
                )
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
                event = ChatStreamEvent(
                    type="message",
                    data={"session_id": session_id, "message": msg.model_dump()},
                )
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

            yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 风险初判：计算中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                risk = detect_risk_snapshot(analyze_text, enable_news_gate=True)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险初判：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 主张抽取：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                claims = orchestrator.run_claims(analyze_text, strategy=risk.strategy)
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 主张抽取：完成（{len(claims)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 联网检索证据：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            evidences = orchestrator.run_evidence(
                text=analyze_text, claims=claims, strategy=risk.strategy
            )
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

            yield f"data: {ChatStreamEvent(type='token', data={'content': '- 证据聚合与对齐：进行中…\n', 'session_id': session_id}).model_dump_json()}\n\n"
            with llm_slot():
                aligned = align_evidences(
                    claims=claims, evidences=evidences, strategy=risk.strategy
                )
            yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

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
                f"- 风险初判: {_zh_risk_label(risk.label)}（score={risk.score}）\n"
                f"- 主张数: {len(claims)}\n"
                f"- 对齐证据数: {len(aligned)}\n"
                f"- 报告风险: {_zh_risk_label(report.get('risk_label'))}（{report.get('risk_score')}）\n"
                f"- 场景: {_zh_scenario(report.get('detected_scenario'))}\n\n"
                "提示：可使用下方命令把本次 record_id 加载到前端上下文进行追问。"
            )

            analyze_actions = base_actions + [
                ChatAction(
                    type="command",
                    label="加载本次结果到前端",
                    command=f"/load_history {record_id}",
                ),
                ChatAction(
                    type="command", label="为什么这样判定", command=f"/why {record_id}"
                ),
            ]

            msg = ChatMessage(
                role="assistant",
                content=content,
                actions=analyze_actions,
                references=top_refs,
            )
            event = ChatStreamEvent(
                type="message",
                data={"session_id": session_id, "message": msg.model_dump()},
            )
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
            logger.error("chat_stream 异常: %s", e)
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
