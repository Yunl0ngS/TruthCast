from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatReference(BaseModel):
    title: str
    href: str
    description: str | None = None


class ChatAction(BaseModel):
    type: Literal["link", "command"]
    label: str
    href: str | None = None
    command: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    actions: list[ChatAction] = Field(default_factory=list)
    references: list[ChatReference] = Field(default_factory=list)


class ChatRequest(BaseModel):
    session_id: str | None = None
    text: str
    context: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    assistant_message: ChatMessage


class ChatStreamEvent(BaseModel):
    type: Literal["token", "message", "done", "error"]
    data: dict[str, Any]

