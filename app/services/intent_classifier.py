"""意图分类模块：将用户自然语言输入映射到工具调用。"""

from __future__ import annotations

import re
from typing import Any, Literal

INTENT_PATTERNS: dict[str, list[str]] = {
    "why": [
        r"为什么.*判定",
        r"为什么.*风险",
        r"怎么得出的.*结论",
        r"判定依据.*是什么",
        r"判定.*原因",
        r"为什么.*这样",
        r"为什么.*结论",
        r"解释.*判定",
        r"解释.*风险",
        r"风险.*来源",
        r"结论.*依据",
    ],
    "compare": [
        r"对比.*上次",
        r"比较.*两条记录",
        r"和之前.*对比",
        r"对比.*历史",
        r"比较.*两次",
        r"上次.*对比",
        r"历史.*对比",
        r"对比分析",
    ],
    "deep_dive": [
        r"深入.*分析",
        r"详细.*证据",
        r"证据.*来源",
        r"主张.*可信",
        r"深入.*证据",
        r"详细.*分析",
        r"展开.*分析",
        r"详细说明",
        r"更详细",
        r"深入看看",
    ],
    "content": [
        r"生成.*应对",
        r"写.*澄清",
        r"应对.*内容",
        r"澄清.*稿",
        r"生成.*声明",
        r"写.*声明",
        r"公关.*稿",
        r"回应.*内容",
    ],
    "more_evidence": [
        r"补充.*证据",
        r"更多.*证据",
        r"再找.*证据",
        r"搜索.*证据",
        r"检索.*证据",
        r"补充检索",
        r"更多来源",
    ],
    "list": [
        r"历史记录",
        r"查看历史",
        r"最近.*记录",
        r"列出.*记录",
        r"有哪些记录",
        r"记录列表",
    ],
    "analyze": [
        r"分析.*文本",
        r"检测.*新闻",
        r"验证.*信息",
        r"核查.*内容",
        r"帮我.*分析",
        r"分析一下",
        r"检测一下",
        r"核查一下",
    ],
    "help": [
        r"怎么用",
        r"帮助",
        r"使用.*方法",
        r"功能.*介绍",
        r"有什么.*功能",
        r"能做什么",
        r"支持.*命令",
    ],
}

IntentName = Literal[
    "why",
    "compare",
    "deep_dive",
    "content",
    "more_evidence",
    "list",
    "analyze",
    "help",
    "unknown",
    "rewrite",
    "load_history",
]


def classify_intent(text: str) -> tuple[IntentName, dict[str, Any]]:
    """将用户输入分类为意图，返回 (intent_name, extracted_args)。

    Phase 1：仅使用规则匹配，覆盖 80% 常见意图。
    Phase 2（可选）：可接入 LLM 处理复杂/模糊输入。
    """
    t = text.strip()

    if not t:
        return ("help", {})

    if t.startswith("/"):
        return _parse_command_intent(t)

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, t, re.IGNORECASE):
                return (intent, {})

    return ("unknown", {})


def _parse_command_intent(text: str) -> tuple[IntentName, dict[str, Any]]:
    """解析显式命令格式（/why, /compare 等）。"""
    t = text.strip()
    parts = re.split(r"\s+", t, maxsplit=3)
    cmd = parts[0].lower() if parts else ""

    if cmd in ("/why", "/explain"):
        record_id = parts[1] if len(parts) >= 2 else ""
        return ("why", {"record_id": record_id})

    if cmd == "/compare":
        record_id_1 = parts[1] if len(parts) >= 2 else ""
        record_id_2 = parts[2] if len(parts) >= 3 else ""
        return ("compare", {"record_id_1": record_id_1, "record_id_2": record_id_2})

    if cmd in ("/deep_dive", "/deepdive"):
        record_id = parts[1] if len(parts) >= 2 else ""
        focus = parts[2] if len(parts) >= 3 else "general"
        claim_index = None
        if len(parts) >= 4:
            try:
                claim_index = int(parts[3])
            except ValueError:
                pass
        return ("deep_dive", {"record_id": record_id, "focus": focus, "claim_index": claim_index})

    if cmd == "/content":
        return ("content", {})

    if cmd in ("/more_evidence", "/more"):
        return ("more_evidence", {})

    if cmd in ("/list", "/history", "/records"):
        limit = 10
        if len(parts) >= 2:
            raw = parts[1].strip()
            if raw.startswith("limit="):
                raw = raw[len("limit="):]
            try:
                limit = int(raw)
            except ValueError:
                limit = 10
        return ("list", {"limit": limit})

    if cmd == "/analyze":
        analyze_text = t[len("/analyze"):].strip() if len(t) > len("/analyze") else ""
        return ("analyze", {"text": analyze_text})

    if cmd == "/help":
        return ("help", {})

    if cmd == "/rewrite":
        style = parts[1] if len(parts) >= 2 else "short"
        return ("rewrite", {"style": style})

    if cmd == "/load_history":
        record_id = parts[1] if len(parts) >= 2 else ""
        return ("load_history", {"record_id": record_id})

    return ("unknown", {"raw_command": cmd})


def build_suggested_actions(
    intent: IntentName,
    record_id: str | None = None,
    risk_score: int | None = None,
    evidence_insufficient_ratio: float | None = None,
) -> list[dict[str, Any]]:
    """根据意图和上下文生成动态建议按钮。"""
    actions: list[dict[str, Any]] = []

    if intent == "why" and record_id:
        actions.append({"type": "command", "label": "深入分析证据", "command": f"/deep_dive {record_id} evidence"})
        if risk_score is not None and risk_score >= 70:
            actions.append({"type": "link", "label": "生成应对内容", "href": "/content"})
        else:
            actions.append({"type": "command", "label": "查看证据来源", "command": f"/deep_dive {record_id} sources"})
            actions.append({"type": "command", "label": "对比历史记录", "command": "/list"})

    elif intent == "deep_dive" and record_id:
        actions.append({"type": "command", "label": "为什么这样判定", "command": f"/why {record_id}"})
        actions.append({"type": "command", "label": "深入其他焦点", "command": f"/deep_dive {record_id} general"})

    elif intent == "compare":
        actions.append({"type": "command", "label": "列出最近记录", "command": "/list"})

    elif intent == "list":
        actions.append({"type": "link", "label": "打开历史记录", "href": "/history"})

    elif intent == "more_evidence" and record_id:
        actions.append({"type": "command", "label": "重试证据检索", "command": "/retry evidence"})
        actions.append({"type": "command", "label": "重试综合报告", "command": "/retry report"})

    if evidence_insufficient_ratio is not None and evidence_insufficient_ratio > 0.5:
        for a in actions[:]:
            if a.get("type") == "command" and "more_evidence" not in a.get("command", ""):
                actions.insert(0, {"type": "command", "label": "补充检索证据", "command": "/more_evidence"})
                break

    return actions
