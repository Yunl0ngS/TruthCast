import time
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.core.concurrency import llm_slot
from app.orchestrator import orchestrator
from app.schemas.chat import ChatAction, ChatMessage, ChatReference, ChatRequest, ChatResponse, ChatStreamEvent
from app.services.history_store import save_report
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot

router = APIRouter(prefix="/chat", tags=["chat"])


def _new_session_id() -> str:
    return f"chat_{int(time.time() * 1000)}"


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

    session_id = payload.session_id or _new_session_id()
    text = payload.text.strip()

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="应对内容", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

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
        f"- 风险快照: {risk.label}（score={risk.score}）\n"
        f"- 主张数: {len(claims)}\n"
        f"- 对齐证据数: {len(aligned)}\n"
        f"- 报告风险: {report.get('risk_label')}（{report.get('risk_score')}）\n"
        f"- 场景: {report.get('detected_scenario')}\n\n"
        "提示：下一步将对接对话工作台的‘加载该 record_id 到上下文’以实现真正追问与迭代。"
    )

    analyze_actions = base_actions + [
        ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
    ]

    msg = ChatMessage(
        role="assistant",
        content=content,
        actions=analyze_actions,
        references=top_refs,
    )
    return ChatResponse(session_id=session_id, assistant_message=msg)


@router.post("/stream")
def chat_stream(payload: ChatRequest) -> StreamingResponse:
    """SSE 流式对话（V1：对齐 /chat 的最小工具编排，逐步输出 token + 最终结构化 message）。

    事件格式：data: {"type":..., "data":...}\n\n
    """

    session_id = payload.session_id or _new_session_id()
    text = payload.text.strip()

    base_actions = [
        ChatAction(type="link", label="打开对话工作台", href="/chat"),
        ChatAction(type="link", label="检测结果", href="/result"),
        ChatAction(type="link", label="舆情预演", href="/simulation"),
        ChatAction(type="link", label="应对内容", href="/content"),
        ChatAction(type="link", label="历史记录", href="/history"),
    ]

    def event_generator() -> Iterator[str]:
        try:
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
                f"- 风险快照: {risk.label}（score={risk.score}）\n"
                f"- 主张数: {len(claims)}\n"
                f"- 对齐证据数: {len(aligned)}\n"
                f"- 报告风险: {report.get('risk_label')}（{report.get('risk_score')}）\n"
                f"- 场景: {report.get('detected_scenario')}\n\n"
                "提示：可使用下方命令把本次 record_id 加载到前端上下文进行追问。"
            )

            analyze_actions = base_actions + [
                ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
            ]

            msg = ChatMessage(
                role="assistant",
                content=content,
                actions=analyze_actions,
                references=top_refs,
            )
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

