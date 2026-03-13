from app.schemas.chat import ChatMessage, ChatStreamEvent
from app.services import chat_store


def _emit_sse_token(session_id: str, content: str) -> str:
    """生成 SSE token 事件字符串。"""
    event = ChatStreamEvent(
        type="token", data={"content": content, "session_id": session_id}
    )
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_stage(session_id: str, stage: str, status: str) -> str:
    """生成 SSE stage 事件字符串。"""
    event = ChatStreamEvent(
        type="stage", data={"session_id": session_id, "stage": stage, "status": status}
    )
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_message(session_id: str, message: ChatMessage) -> str:
    """生成 SSE message 事件字符串。"""
    event = ChatStreamEvent(
        type="message", data={"session_id": session_id, "message": message.model_dump()}
    )
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_done(session_id: str) -> str:
    """生成 SSE done 事件字符串。"""
    event = ChatStreamEvent(type="done", data={"session_id": session_id})
    return f"data: {event.model_dump_json()}\n\n"


def _emit_sse_error(session_id: str, error_message: str) -> str:
    """生成 SSE error 事件字符串。"""
    event = ChatStreamEvent(
        type="error", data={"session_id": session_id, "message": error_message}
    )
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
