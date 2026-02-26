"""Unified CLI renderer for chat SSE events.

Provides consistent, GBK-safe rendering for stage/token/message/error blocks.
"""

from __future__ import annotations

from typing import Any

from app.cli.lib.safe_output import emoji, safe_print


class ChatRenderer:
    """Render chat stream events with stable block structure."""

    _STAGE_EMOJI = {
        "risk": emoji("🔍", "[RISK]"),
        "claims": emoji("📋", "[CLAIMS]"),
        "evidence_search": emoji("🌐", "[SEARCH]"),
        "evidence_align": emoji("🔗", "[ALIGN]"),
        "report": emoji("📊", "[REPORT]"),
        "simulation": emoji("🎭", "[SIM]"),
        "content": emoji("✍️", "[WRITE]"),
    }

    _STATUS_EMOJI = {
        "running": emoji("⏳", "[LOADING]"),
        "done": emoji("✅", "[DONE]"),
        "failed": emoji("❌", "[FAILED]"),
    }

    _STAGE_NAME = {
        "risk": "风险快照",
        "claims": "主张抽取",
        "evidence_search": "证据检索",
        "evidence_align": "证据对齐",
        "report": "综合报告",
        "simulation": "舆情预演",
        "content": "应对内容",
    }

    def render_token(self, content: str) -> None:
        """Render incremental token without newline."""
        safe_print(content, end="", flush=True)

    def render_stage(self, stage: str, status: str) -> None:
        """Render stage status line."""
        stage_mark = self._STAGE_EMOJI.get(stage, emoji("📌", "[MARK]"))
        status_mark = self._STATUS_EMOJI.get(status, "")
        name = self._STAGE_NAME.get(stage, stage)

        if status == "running":
            safe_print(f"\n{stage_mark} {name}中...")
        elif status == "done":
            safe_print(f"{status_mark} {name}完成")
        elif status == "failed":
            safe_print(f"{status_mark} {name}失败")

    def render_message(self, message: dict[str, Any]) -> None:
        """Render full assistant message block with separators."""
        content = message.get("content", "")
        actions = message.get("actions", [])
        references = message.get("references", [])

        safe_print("\n" + "-" * 60)
        if content:
            safe_print(content)

        if actions:
            safe_print("\n[相关操作]")
            for action in actions:
                label = action.get("label", "")
                command = action.get("command", "")
                href = action.get("href", "")

                if command:
                    safe_print(f"  - {label}: {command}")
                elif href:
                    safe_print(f"  - {label}: {href}")

        if references:
            safe_print("\n[参考链接]")
            for ref in references[:5]:
                title = ref.get("title", "")
                href = ref.get("href", "")
                description = ref.get("description", "")

                safe_print(f"  - {title}")
                if href:
                    safe_print(f"    {href}")
                if description:
                    safe_print(f"    {description}")
        safe_print("-" * 60)

    def render_error(self, error_msg: str) -> None:
        """Render error block."""
        safe_print(f"\n{emoji('❌', '[ERROR]')} 错误: {error_msg}")
