import hashlib
import json
import os
import time
from typing import Any, Optional

from fastapi.encoders import jsonable_encoder

from app.schemas.chat import ChatAction, ChatMessage
from app.services import chat_store


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


def _new_session_id() -> str:
    return f"chat_{int(time.time() * 1000)}"


def _ensure_session(session_id: Optional[str]) -> str:
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


def _build_missing_dependency_message(
    *, tool_name: str, detail: str, suggestion: str
) -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=f"{tool_name} 无法执行：{detail}\n\n建议：{suggestion}",
        actions=[ChatAction(type="command", label="查看帮助", command="/help")],
        references=[],
    )
