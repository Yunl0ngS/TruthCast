"""意图分类模块：将用户自然语言输入映射到工具调用。"""

from __future__ import annotations

import os
import re
from typing import Any, Literal, cast

import httpx

from app.services.json_utils import safe_json_loads

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
        r"对外.*回应",
        r"回应.*稿",
    ],
    "claims_only": [
        r"只帮我提取.*主张",
        r"只提取.*主张",
        r"仅提取.*主张",
        r"提取.*主张",
        r"先提取.*主张",
        r"抽取.*主张",
        r"提取.*主张列表",
        r"主张抽取",
        r"只要.*主张",
        r"仅要.*主张",
        r"列出.*主张",
        r"给我.*主张",
    ],
    "evidence_only": [
        r"检索.*证据",
        r"搜集.*证据",
        r"只检索.*证据",
        r"仅检索.*证据",
        r"只找.*证据",
        r"补充.*检索证据",
        r"先查.*证据",
        r"证据检索",
        r"查证据",
        r"联网查.*证据",
        r"找来源.*证据",
        r"先搜.*证据",
    ],
    "align_only": [
        r"只做.*对齐",
        r"仅做.*对齐",
        r"证据对齐",
        r"先对齐.*证据",
        r"做下.*对齐",
        r"对齐.*主张.*证据",
        r"只要.*对齐结果",
        r"仅要.*对齐结果",
        r"执行.*align",
        r"跑.*对齐",
    ],
    "report_only": [
        r"只生成.*报告",
        r"仅生成.*报告",
        r"报告详情",
        r"生成.*综合报告",
        r"输出.*报告",
        r"只要.*报告",
        r"仅要.*报告",
        r"给我.*报告",
        r"先出.*报告",
        r"报告阶段",
    ],
    "simulate": [
        r"舆情预演",
        r"舆论预演",
        r"预演.*传播",
        r"做.*预演",
        r"模拟.*舆情",
        r"模拟.*传播",
        r"风险传播.*模拟",
        r"跑.*模拟",
        r"生成.*预演",
        r"情绪分布.*预测",
    ],
    "more_evidence": [
        r"补充.*证据",
        r"更多.*证据",
        r"再找.*证据",
        r"搜索.*更多证据",
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
    "claims_only",
    "evidence_only",
    "align_only",
    "report_only",
    "simulate",
    "unknown",
    # 下列意图仅支持命令格式，不在自然语言识别范围内
    "rewrite",
    "load_history",
]


_INTENT_LLM_ALLOWED_INTENTS: set[str] = {
    "why",
    "compare",
    "deep_dive",
    "content",
    "more_evidence",
    "list",
    "analyze",
    "help",
    "claims_only",
    "evidence_only",
    "align_only",
    "report_only",
    "simulate",
}

_TOOL_INTENT_MAP: dict[str, str] = {
    "content_generate": "content",
    "claims_only": "claims_only",
    "evidence_only": "evidence_only",
    "align_only": "align_only",
    "report_only": "report_only",
    "simulate": "simulate",
    "analyze": "analyze",
    "why": "why",
    "compare": "compare",
    "deep_dive": "deep_dive",
    "list": "list",
    "help": "help",
    "more_evidence": "more_evidence",
}


def _intent_llm_enabled() -> bool:
    raw = (os.getenv("TRUTHCAST_CHAT_INTENT_LLM_ENABLED") or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _intent_llm_first_enabled() -> bool:
    raw = (os.getenv("TRUTHCAST_CHAT_INTENT_LLM_FIRST") or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _intent_llm_timeout_sec() -> float:
    raw = (os.getenv("TRUTHCAST_CHAT_INTENT_LLM_TIMEOUT_SEC") or "12").strip()
    try:
        return max(3.0, min(60.0, float(raw)))
    except ValueError:
        return 12.0


def _intent_llm_base_url() -> str:
    base = (
        os.getenv("TRUTHCAST_CHAT_INTENT_LLM_BASE_URL")
        or os.getenv("TRUTHCAST_LLM_BASE_URL")
        or "https://api.openai.com/v1"
    ).strip()
    return base.rstrip("/")


def _intent_llm_api_key() -> str:
    return (
        os.getenv("TRUTHCAST_CHAT_INTENT_LLM_API_KEY")
        or os.getenv("TRUTHCAST_LLM_API_KEY")
        or ""
    ).strip()


def _intent_llm_model() -> str:
    return (
        os.getenv("TRUTHCAST_CHAT_INTENT_LLM_MODEL")
        or os.getenv("TRUTHCAST_LLM_MODEL")
        or "gpt-4o-mini"
    ).strip()


def _normalize_intent_args(intent: str, args: dict[str, Any], text: str) -> dict[str, Any]:
    if intent in {"analyze", "claims_only", "evidence_only"}:
        candidate = args.get("text")
        content = candidate.strip() if isinstance(candidate, str) else ""
        return {"text": content or text}

    if intent in {"align_only", "report_only", "simulate", "why", "more_evidence"}:
        rid = args.get("record_id")
        return {"record_id": rid.strip() if isinstance(rid, str) else ""}

    if intent == "list":
        limit = args.get("limit", 10)
        try:
            return {"limit": int(limit)}
        except (TypeError, ValueError):
            return {"limit": 10}

    if intent == "compare":
        rid1 = args.get("record_id_1")
        rid2 = args.get("record_id_2")
        return {
            "record_id_1": rid1.strip() if isinstance(rid1, str) else "",
            "record_id_2": rid2.strip() if isinstance(rid2, str) else "",
        }

    if intent == "deep_dive":
        rid = args.get("record_id")
        focus = args.get("focus", "general")
        claim_index = args.get("claim_index")
        normalized: dict[str, Any] = {
            "record_id": rid.strip() if isinstance(rid, str) else "",
            "focus": focus.strip() if isinstance(focus, str) else "general",
        }
        if claim_index is not None:
            try:
                normalized["claim_index"] = int(claim_index)
            except (TypeError, ValueError):
                pass
        return normalized

    if intent == "content":
        style = args.get("style", "formal")
        if not isinstance(style, str) or not style.strip():
            style = "formal"
        return {"style": style.strip().lower()}

    return {}


def _classify_intent_with_llm(text: str) -> tuple[IntentName, dict[str, Any]]:
    api_key = _intent_llm_api_key()
    if not api_key:
        return ("unknown", {})

    payload = {
        "model": _intent_llm_model(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是意图分类器。根据用户输入返回 JSON，且仅输出 JSON。\n"
                    "JSON schema: {\"intent\": string, \"args\": object}\n"
                    "allowed intents: why, compare, deep_dive, content, more_evidence, list, analyze, help, "
                    "claims_only, evidence_only, align_only, report_only, simulate, unknown。\n"
                    "如果无法判断，intent=unknown。不要输出额外文本。"
                ),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=_intent_llm_timeout_sec()) as client:
            resp = client.post(
                f"{_intent_llm_base_url()}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
    except Exception:
        return ("unknown", {})

    parsed = safe_json_loads(content, context="intent_classifier.llm")
    if not isinstance(parsed, dict):
        return ("unknown", {})

    raw_intent = parsed.get("intent")
    if not isinstance(raw_intent, str) or not raw_intent.strip():
        raw_tool = parsed.get("tool")
        if isinstance(raw_tool, str):
            raw_intent = _TOOL_INTENT_MAP.get(raw_tool.strip().lower(), "unknown")
        else:
            raw_intent = "unknown"

    intent = raw_intent.strip().lower()
    if intent not in _INTENT_LLM_ALLOWED_INTENTS:
        return ("unknown", {})

    args = parsed.get("args")
    if not isinstance(args, dict):
        args = {}

    normalized = _normalize_intent_args(intent, args, text)
    return (cast(IntentName, intent), normalized)


def classify_intent(text: str) -> tuple[IntentName, dict[str, Any]]:
    """将用户输入分类为意图，返回 (intent_name, extracted_args)。

    默认策略：LLM-first（每条非命令输入先走 LLM），规则作为兜底。
    兼容策略：可通过环境变量切回规则优先。
    """
    t = text.strip()

    if not t:
        return ("help", {})

    if t.startswith("/"):
        return _parse_command_intent(t)

    llm_first = _intent_llm_first_enabled()
    llm_enabled = _intent_llm_enabled()

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, t, re.IGNORECASE):
                return (cast(IntentName, intent), {})

    if llm_enabled and llm_first:
        llm_intent, llm_args = _classify_intent_with_llm(t)
        if llm_intent != "unknown":
            return (llm_intent, llm_args)

    if llm_enabled and not llm_first:
        llm_intent, llm_args = _classify_intent_with_llm(t)
        if llm_intent != "unknown":
            return (llm_intent, llm_args)

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
