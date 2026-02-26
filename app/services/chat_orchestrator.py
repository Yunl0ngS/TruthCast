from __future__ import annotations

import re
from typing import Any, Iterator, Literal

from pydantic import BaseModel, Field

from app.core.concurrency import llm_slot
from app.core.guardrails import (
    build_guardrails_warning_message,
    sanitize_text,
    validate_tool_call,
)
from app.orchestrator import orchestrator
from app.schemas.chat import ChatAction, ChatMessage, ChatReference, ChatStreamEvent
from app.services.history_store import get_history, list_history, save_report
from app.services.intent_classifier import (
    IntentName,
    build_suggested_actions,
    classify_intent,
)
from app.services.pipeline import align_evidences
from app.services.risk_snapshot import detect_risk_snapshot


class ToolAnalyzeArgs(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class ToolLoadHistoryArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)


class ToolWhyArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)


class ToolListArgs(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class ToolMoreEvidenceArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)


class ToolRewriteArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)
    style: str = Field(default="short", max_length=32)


class ToolCompareArgs(BaseModel):
    record_id_1: str = Field(min_length=1, max_length=128)
    record_id_2: str = Field(min_length=1, max_length=128)


class ToolDeepDiveArgs(BaseModel):
    record_id: str = Field(min_length=1, max_length=128)
    focus: str = Field(default="general", max_length=32)
    claim_index: int | None = Field(default=None, ge=0)


class ToolClaimsOnlyArgs(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


class ToolEvidenceOnlyArgs(BaseModel):
    text: str = Field(min_length=1, max_length=12000)
    record_id: str = Field(default="", max_length=128)


class ToolAlignOnlyArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=12000)


class ToolReportOnlyArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=12000)
    persist: bool = Field(default=False, description="是否写入历史记录")


class ToolSimulateArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)
    text: str = Field(default="", max_length=12000)


class ToolContentGenerateArgs(BaseModel):
    record_id: str = Field(default="", max_length=128)
    style: str = Field(default="formal", max_length=32)
    text: str = Field(default="", max_length=12000)
    detail: str = Field(default="full", max_length=16)
    force: bool = Field(default=False)
    reuse_only: bool = Field(default=False)
    operation: str = Field(default="generate", max_length=16)
    section: str = Field(default="", max_length=32)
    variant: str = Field(default="", max_length=32)
    faq_range: str = Field(default="", max_length=32)
    platforms: str = Field(default="", max_length=128)

ToolName = Literal[
    "analyze",
    "load_history",
    "why",
    "list",
    "more_evidence",
    "rewrite",
    "compare",
    "deep_dive",
    "help",
    "export",
    "claims_only",
    "evidence_only",
    "align_only",
    "report_only",
    "simulate",
    "content_generate",
]


def _is_analyze_intent(text: str) -> bool:
    t = text.strip()
    return t.startswith("/analyze")


def _extract_analyze_text(text: str) -> str:
    t = text.strip()
    if t.startswith("/analyze"):
        return t[len("/analyze") :].strip()
    return t


def _extract_payload_text(raw_text: str) -> str:
    text = raw_text.strip()
    for sep in ("：", ":"):
        if sep in text:
            _, right = text.split(sep, 1)
            candidate = right.strip()
            if candidate:
                return candidate
    return text


def _extract_payload_text_if_explicit(raw_text: str, min_len: int = 20) -> str:
    text = raw_text.strip()
    for sep in ("：", ":"):
        if sep in text:
            _, right = text.split(sep, 1)
            candidate = right.strip()
            if len(candidate) >= min_len:
                return candidate
            return ""
    return ""


def _parse_bool_flag(raw: str) -> bool:
    value = (raw or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _parse_command_kv(tokens: list[str]) -> dict[str, str]:
    kv: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        key_norm = key.strip().lower()
        if key_norm:
            kv[key_norm] = value.strip()
    return kv


def parse_tool(text: str, session_meta: dict[str, Any] | None = None) -> tuple[ToolName, dict[str, Any]]:
    """把用户输入解析为后端允许的工具调用。

    约束：只允许白名单工具。
    支持意图识别（自然语言 -> 工具映射）。
    """

    t = text.strip()
    if not t:
        return ("help", {})

    meta = session_meta or {}

    if t.startswith("/load_history"):
        parts = re.split(r"\s+", t)
        record_id = parts[1] if len(parts) >= 2 else ""
        return ("load_history", {"record_id": record_id})

    if t.startswith("/why") or t.startswith("/explain"):
        parts = re.split(r"\s+", t)
        record_id = parts[1] if len(parts) >= 2 else ""
        if not record_id:
            record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("why", {"record_id": record_id})

    if t.startswith("/list") or t.startswith("/history") or t.startswith("/records"):
        parts = re.split(r"\s+", t)
        limit = 10
        if len(parts) >= 2:
            raw = parts[1].strip()
            if raw.startswith("limit="):
                raw = raw[len("limit=") :]
            try:
                limit = int(raw)
            except ValueError:
                limit = 10
        return ("list", {"limit": limit})

    if t.startswith("/more_evidence") or t.startswith("/more"):
        record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("more_evidence", {"record_id": record_id})

    if t.startswith("/rewrite"):
        parts = re.split(r"\s+", t)
        style = parts[1].strip() if len(parts) >= 2 else "short"
        if style.startswith("style="):
            style = style[len("style=") :]
        record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("rewrite", {"record_id": record_id, "style": style})

    if t.startswith("/compare"):
        parts = re.split(r"\s+", t)
        record_id_1 = parts[1] if len(parts) >= 2 else ""
        record_id_2 = parts[2] if len(parts) >= 3 else ""
        bound_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        if not record_id_1 and bound_id:
            record_id_1 = bound_id
        return ("compare", {"record_id_1": record_id_1, "record_id_2": record_id_2})

    if t.startswith("/deep_dive") or t.startswith("/deepdive"):
        parts = re.split(r"\s+", t)
        record_id = parts[1] if len(parts) >= 2 else ""
        focus = parts[2] if len(parts) >= 3 else "general"
        claim_index = None
        if len(parts) >= 4:
            try:
                claim_index = int(parts[3])
            except ValueError:
                pass
        if not record_id:
            record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("deep_dive", {"record_id": record_id, "focus": focus, "claim_index": claim_index})

    if t.startswith("/claims_only") or t.startswith("/claims-only"):
        value = t.split(" ", 1)
        claim_text = value[1].strip() if len(value) >= 2 else ""
        return ("claims_only", {"text": claim_text})

    if t.startswith("/evidence_only") or t.startswith("/evidence-only"):
        value = t.split(" ", 1)
        evidence_text = value[1].strip() if len(value) >= 2 else ""
        fallback_record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("evidence_only", {"text": evidence_text, "record_id": fallback_record_id})

    if t.startswith("/align_only") or t.startswith("/align-only"):
        parts = re.split(r"\s+", t)
        record_id = parts[1].strip() if len(parts) >= 2 else ""
        if not record_id:
            record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("align_only", {"record_id": record_id})

    if t.startswith("/report_only") or t.startswith("/report-only"):
        parts = re.split(r"\s+", t)
        record_id = parts[1].strip() if len(parts) >= 2 else ""
        if not record_id:
            record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("report_only", {"record_id": record_id})

    if t.startswith("/simulate"):
        parts = re.split(r"\s+", t)
        record_id = parts[1].strip() if len(parts) >= 2 else ""
        if not record_id:
            record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        return ("simulate", {"record_id": record_id})

    if t.startswith("/content_generate") or t.startswith("/content-generate") or (t.startswith("/content") and not t.startswith("/content_show") and not t.startswith("/content-show")):
        parts = re.split(r"\s+", t)
        record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")
        kv = _parse_command_kv(parts[1:])
        style = kv.get("style", "formal")
        detail = kv.get("detail", "full")
        force = _parse_bool_flag(kv.get("force", "false"))
        reuse_only = _parse_bool_flag(kv.get("reuse_only", "false"))
        text_arg = kv.get("text", "")
        operation = "generate"
        if t.startswith("/content") and not t.startswith("/content_generate") and not t.startswith("/content-generate"):
            operation = "generate" if force else "show"
        return (
            "content_generate",
            {
                "record_id": record_id,
                "style": style,
                "detail": detail,
                "force": force,
                "reuse_only": reuse_only,
                "text": text_arg,
                "operation": operation,
            },
        )

    if t.startswith("/content_show") or t.startswith("/content-show"):
        parts = re.split(r"\s+", t)
        section = parts[1].strip().lower() if len(parts) >= 2 else ""
        variant = parts[2].strip().lower() if len(parts) >= 3 else ""
        kv = _parse_command_kv(parts[1:])
        faq_range = kv.get("range", variant if section == "faq" else "")
        platforms = kv.get("platforms", variant if section == "scripts" else "")
        return (
            "content_generate",
            {
                "operation": "show",
                "section": section,
                "variant": variant,
                "faq_range": faq_range,
                "platforms": platforms,
                "detail": kv.get("detail", "full"),
                "style": kv.get("style", "formal"),
                "record_id": str(meta.get("record_id") or meta.get("bound_record_id") or ""),
            },
        )

    if _is_analyze_intent(t):
        analyze_text = _extract_analyze_text(t)
        return ("analyze", {"text": analyze_text})

    intent, intent_args = classify_intent(t)
    tool_name = _intent_to_tool(intent)
    # 路由保护：当用户给出“检索/搜集证据 + 长文本载荷”时，优先执行 evidence_only，
    # 避免误路由到 more_evidence（建议模式）。
    if tool_name == "more_evidence":
        payload_text = _extract_payload_text(t)
        if payload_text and payload_text != t and len(payload_text) >= 30:
            return ("evidence_only", {"text": payload_text, "record_id": str(meta.get("record_id") or meta.get("bound_record_id") or "")})
    if tool_name != "help":
        args = _merge_intent_args(tool_name, intent_args, meta, t)
        return (tool_name, args)

    return ("help", {"clarify": True, "text": t})


def _intent_to_tool(intent: IntentName) -> ToolName:
    """将意图名称映射到工具名称。
    注意:
    - content: 映射到 content_generate（V2已完成后端独立工具）
    - rewrite/load_history: 仅支持命令格式（/rewrite, /load_history），不在意图识别范围内
    """
    mapping: dict[IntentName, ToolName] = {
        "why": "why",
        "compare": "compare",
        "deep_dive": "deep_dive",
        "content": "content_generate",  # 修复：content 现在映射到 content_generate 独立工具
        "more_evidence": "more_evidence",
        "list": "list",
        "analyze": "analyze",
        "claims_only": "claims_only",
        "evidence_only": "evidence_only",
        "align_only": "align_only",
        "report_only": "report_only",
        "simulate": "simulate",
        "help": "help",
        "unknown": "help",
    }
    return mapping.get(intent, "help")


def _merge_intent_args(
    tool_name: ToolName,
    intent_args: dict[str, Any],
    meta: dict[str, Any],
    raw_text: str,
) -> dict[str, Any]:
    """合并意图参数与 session meta。"""
    bound_record_id = str(meta.get("record_id") or meta.get("bound_record_id") or "")

    if tool_name == "why":
        record_id = intent_args.get("record_id") or bound_record_id
        return {"record_id": record_id}

    if tool_name == "deep_dive":
        record_id = intent_args.get("record_id") or bound_record_id
        return {
            "record_id": record_id,
            "focus": intent_args.get("focus", "general"),
            "claim_index": intent_args.get("claim_index"),
        }

    if tool_name == "compare":
        record_id_1 = intent_args.get("record_id_1") or bound_record_id
        return {"record_id_1": record_id_1, "record_id_2": intent_args.get("record_id_2", "")}

    if tool_name == "more_evidence":
        record_id = intent_args.get("record_id") or bound_record_id
        return {"record_id": record_id}

    if tool_name == "list":
        return {"limit": intent_args.get("limit", 10)}

    if tool_name == "analyze":
        text = str(intent_args.get("text") or "").strip() or _extract_payload_text(raw_text)
        return {"text": text}

    if tool_name == "claims_only":
        text = str(intent_args.get("text") or "").strip() or _extract_payload_text(raw_text)
        return {"text": text}

    if tool_name == "evidence_only":
        text = str(intent_args.get("text") or "").strip() or _extract_payload_text(raw_text)
        return {
            "text": text,
            "record_id": intent_args.get("record_id") or bound_record_id,
        }

    if tool_name in {"align_only", "report_only", "simulate"}:
        text = str(intent_args.get("text") or "").strip() or _extract_payload_text(raw_text)
        return {"record_id": intent_args.get("record_id") or bound_record_id, "text": text}

    if tool_name == "content_generate":
        explicit_text = str(intent_args.get("text") or "").strip()
        text = explicit_text or _extract_payload_text_if_explicit(raw_text)
        return {
            "record_id": intent_args.get("record_id") or bound_record_id,
            "style": intent_args.get("style", "formal"),
            "text": text,
            "detail": intent_args.get("detail", "full"),
            "force": bool(intent_args.get("force", False)),
            "reuse_only": bool(intent_args.get("reuse_only", False)),
            "operation": intent_args.get("operation", "generate"),
            "section": intent_args.get("section", ""),
            "variant": intent_args.get("variant", ""),
            "faq_range": intent_args.get("faq_range", ""),
            "platforms": intent_args.get("platforms", ""),
        }

    return intent_args


def build_intent_clarify_message(raw_text: str) -> ChatMessage:
    preview = _extract_payload_text(raw_text)
    if len(preview) > 180:
        preview = preview[:177] + "..."
    return ChatMessage(
        role="assistant",
        content=(
            "我收到一段文本，但当前意图还不够明确。\n\n"
            "你希望我怎么处理这段内容？\n"
            "- 做完整分析（风险快照->主张->证据->对齐->报告）\n"
            "- 或直接选择单技能（主张/证据/对齐/报告/预演/应对内容）\n\n"
            f"文本预览：{preview}"
        ),
        actions=[
            ChatAction(type="command", label="完整分析", command=f"/analyze {preview}"),
            ChatAction(type="command", label="仅提取主张", command=f"/claims_only {preview}"),
            ChatAction(type="command", label="仅检索证据", command=f"/evidence_only {preview}"),
            ChatAction(type="command", label="仅证据对齐", command="/align_only"),
            ChatAction(type="command", label="仅生成报告", command="/report_only"),
            ChatAction(type="command", label="仅舆情预演", command="/simulate"),
            ChatAction(type="command", label="仅应对内容", command="/content_generate"),
            ChatAction(type="command", label="解释判定原因", command="/why"),
            ChatAction(type="command", label="补充更多证据", command="/more_evidence"),
            ChatAction(type="command", label="改写解释版本", command="/rewrite short"),
            ChatAction(type="command", label="深入分析焦点", command="/deep_dive"),
            ChatAction(type="command", label="对比两条记录", command="/compare"),
            ChatAction(type="command", label="加载历史记录", command="/load_history"),
            ChatAction(type="command", label="查看历史记录", command="/list"),
            ChatAction(type="command", label="查看帮助", command="/help"),
        ],
        references=[],
        meta={"intent": "clarify", "input_preview": preview},
    )


def build_help_message() -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=(
            "当前对话工作台已启用后端工具白名单编排（V2）。\n\n"
            "可用命令：\n"
            "- /analyze <待分析文本>：发起全链路分析\n"
            "- /load_history <record_id>：加载历史记录到前端上下文（仅命令）\n"
            "- /why <record_id>：解释为什么给出该风险/结论（支持自然语言：“为什么判定高风险”）\n"
            "- /list [N]：列出最近 N 条历史记录的 record_id（默认 10，例如 /list 20）\n"
            "- /more_evidence：基于当前上下文，给出补充证据的下一步动作\n"
            "- /rewrite [short|neutral|friendly]：改写解释版本（仅命令）\n"
            "- /compare <record_id_1> <record_id_2>：对比两条历史记录的分析结果\n"
            "- /deep_dive <record_id> [focus] [claim_index]：深入分析某一焦点领域\n"
            "  - focus 可选：general（默认）/evidence/claims/timeline/sources\n"
            "  - claim_index：指定深入分析第几条主张（从0开始）\n\n"
            "- /claims_only <文本>：仅提取主张\n"
            "- /evidence_only <文本>：仅检索证据（复用会话主张）\n"
            "- /align_only [record_id]：仅做证据对齐\n"
            "- /report_only [record_id]：仅生成报告\n"
            "- /simulate [record_id]：仅执行舆情预演\n"
            "- /content_generate [style=...]：仅生成应对内容\n\n"
            "- /content [style=... detail=brief|full force=true|false reuse_only=true|false]：CLI 友好应对内容\n"
            "- /content_show clarification short|medium|long：查看澄清稿指定版本\n"
            "- /content_show faq 1-5：查看 FAQ 区间\n"
            "- /content_show scripts weibo,wechat：查看指定平台话术\n\n"
            "标注「仅命令」的工具不支持自然语言，其他工具均支持自然语言表达。\n\n"
            "record_id 来源：分析完成后会写入历史记录；也可以用 /list 查询后再 /load_history {record_id}。\n\n"
            "你也可以直接粘贴长文本（系统会先询问你要完整分析还是单技能处理）。"
        ),
        actions=[
            ChatAction(type="link", label="检测结果", href="/result"),
            ChatAction(type="link", label="历史记录", href="/history"),
        ],
        references=[],
    )


def build_why_usage_message() -> ChatMessage:
    return ChatMessage(
        role="assistant",
        content=(
            "用法：/why <record_id>\n\n"
            "- 先使用 /list 查看最近的 record_id\n"
            "- 或先 /load_history <record_id> 加载到前端上下文后再追问\n"
        ),
        actions=[
            ChatAction(type="command", label="列出最近记录（/list）", command="/list"),
            ChatAction(type="link", label="打开历史记录页面", href="/history"),
        ],
        references=[],
    )


def run_more_evidence(args: ToolMoreEvidenceArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    return ChatMessage(
        role="assistant",
        content=(
            "补充证据建议（V1）：\n"
            "- 点击下方按钮重试【证据检索】阶段，以获取更多候选证据\n"
            "- 若证据已更新，可再重试【综合报告】阶段刷新结论\n"
        ),
        actions=[
            ChatAction(type="command", label="重试证据检索（/retry evidence）", command="/retry evidence"),
            ChatAction(type="command", label="重试综合报告（/retry report）", command="/retry report"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=[
            ChatReference(
                title=f"历史记录：{record['id']}",
                href="/history",
                description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
            )
        ],
        meta={"record_id": record["id"]},
    )


def run_rewrite(args: ToolRewriteArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    style = (args.style or "short").strip().lower()
    if style not in {"short", "neutral", "friendly"}:
        style = "short"

    detect_data = record.get("detect_data") or {}
    report = record.get("report") or {}
    reasons = detect_data.get("reasons") or []
    suspicious_points = report.get("suspicious_points") or []

    risk_label = report.get("risk_label", record.get("risk_label"))
    risk_score = report.get("risk_score", record.get("risk_score"))

    if style == "short":
        content = (
            f"改写（短版）：结论为【{risk_label}】（score={risk_score}）。\n"
            + ("风险快照原因：" + "；".join([str(x) for x in reasons[:3]]) + "\n" if reasons else "")
            + ("可疑点：" + "；".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
            + "（提示：可用 /more_evidence 或 /retry evidence 补充证据）"
        )
    elif style == "friendly":
        content = (
            f"改写（亲切版）：目前的辅助判断是【{risk_label}】（score={risk_score}）。\n"
            "我主要参考了风险快照的触发原因，以及报告里整理的可疑点/证据对齐结果。\n"
            + ("你可以重点留意：\n- " + "\n- ".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
            + "如果你希望我再多找一些证据，可以直接输入 /more_evidence。"
        )
    else:
        content = (
            f"改写（中性版）：综合判断为【{risk_label}】（score={risk_score}）。\n"
            "依据来源：风险快照触发原因 + 报告可疑点 + 主张-证据对齐结果。\n"
            + ("风险快照原因（节选）：\n- " + "\n- ".join([str(x) for x in reasons[:3]]) + "\n" if reasons else "")
            + ("报告可疑点（节选）：\n- " + "\n- ".join([str(x) for x in suspicious_points[:3]]) + "\n" if suspicious_points else "")
        )

    return ChatMessage(
        role="assistant",
        content=content,
        actions=[
            ChatAction(type="command", label="补充证据（/more_evidence）", command="/more_evidence"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=[
            ChatReference(
                title=f"历史记录：{record['id']}",
                href="/history",
                description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
            )
        ],
        meta={"record_id": record["id"], "style": style},
    )


def run_load_history(args: ToolLoadHistoryArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record['id']}",
            href="/history",
            description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
        )
    ]

    return ChatMessage(
        role="assistant",
        content=(
            "已定位到历史记录。你可以点击下方命令，将其加载到前端上下文（pipeline-store），然后到结果页查看模块化结果。"
        ),
        actions=[
            ChatAction(type="command", label="加载到前端上下文", command=f"/load_history {record['id']}"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=refs,
        meta={"record_id": record["id"]},
    )


def _calc_evidence_insufficient_ratio(claim_reports: list[dict[str, Any]]) -> float:
    """计算证据不足的比例。"""
    if not claim_reports:
        return 0.0
    total = 0
    insufficient = 0
    for cr in claim_reports:
        for ev in cr.get("evidences", []):
            total += 1
            if ev.get("stance") == "insufficient_evidence":
                insufficient += 1
    if total == 0:
        return 0.0
    return insufficient / total


def run_why(args: ToolWhyArgs) -> ChatMessage:
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}。",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    detect_data = record.get("detect_data") or {}
    report = record.get("report") or {}

    reasons = detect_data.get("reasons") or []
    suspicious_points = report.get("suspicious_points") or []
    claim_reports = report.get("claim_reports") or []

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record['id']}",
            href="/history",
            description=f"风险: {record.get('risk_label')}（{record.get('risk_score')}） · 时间: {record.get('created_at')}",
        )
    ]

    seen_urls: set[str] = set()
    for row in claim_reports[:3]:
        for ev in (row.get("evidences") or [])[:3]:
            url = str(ev.get("url") or "").strip()
            title = str(ev.get("title") or url).strip()
            if not url or not url.startswith("http"):
                continue
            if url in seen_urls:
                continue
            seen_urls.add(url)
            refs.append(
                ChatReference(
                    title=title[:80] or url,
                    href=url,
                    description=f"证据立场: {ev.get('stance')} · 置信度: {ev.get('alignment_confidence')}",
                )
            )
            if len(refs) >= 8:
                break
        if len(refs) >= 8:
            break

    # ====== 结构化 blocks（供前端做“引用卡片/折叠区块”展示）======
    # 约定：写入 ChatMessage.meta.blocks，不改动顶层 schema，便于渐进增强与持久化。
    blocks: list[dict[str, Any]] = []

    if reasons:
        blocks.append(
            {
                "kind": "section",
                "title": "风险快照触发原因",
                "items": [str(r) for r in reasons[:5]],
                "collapsed": False,
            }
        )
    if suspicious_points:
        blocks.append(
            {
                "kind": "section",
                "title": "报告可疑点",
                "items": [str(p) for p in suspicious_points[:5]],
                "collapsed": True,
            }
        )
    if claim_reports:
        items: list[str] = []
        for row in claim_reports[:3]:
            claim_text = (row.get("claim") or {}).get("claim_text") or ""
            verdict = row.get("verdict") or ""
            items.append(f"主张：{claim_text[:60]}… → 结论：{verdict}")
        if items:
            blocks.append(
                {
                    "kind": "section",
                    "title": "主张级证据对齐（节选）",
                    "items": items,
                    "collapsed": True,
                }
            )

    # refs[0] 是历史记录入口；其余多为证据链接
    if len(refs) > 1:
        blocks.append(
            {
                "kind": "links",
                "title": f"证据链接（节选 {len(refs) - 1} 条）",
                "links": [r.model_dump() for r in refs[1:]],
                "collapsed": True,
            }
        )

    lines: list[str] = []
    lines.append("解释（最小可用）：本结论来自风险快照 + 报告阶段对主张与证据的综合判断。")
    lines.append("")
    lines.append(
        f"- 风险快照：{detect_data.get('label', record.get('risk_label'))}（score={detect_data.get('score', record.get('risk_score'))}）"
    )
    if reasons:
        lines.append("  - 触发原因：")
        for r in reasons[:5]:
            lines.append(f"    - {r}")

    lines.append(
        f"- 综合报告：{report.get('risk_label', record.get('risk_label'))}（score={report.get('risk_score', record.get('risk_score'))}）"
    )
    if suspicious_points:
        lines.append("  - 可疑点摘要：")
        for p in suspicious_points[:5]:
            lines.append(f"    - {p}")

    if claim_reports:
        lines.append("  - 主张级证据对齐（节选）：")
        for row in claim_reports[:3]:
            claim_text = (row.get("claim") or {}).get("claim_text") or ""
            verdict = row.get("verdict") or ""
            lines.append(f"    - 主张：{claim_text[:60]}… → 结论：{verdict}")

    lines.append("")
    lines.append("提示：你可以先加载该 record_id 到前端上下文，再打开结果页查看完整模块化结果与证据链。")

    risk_score_val = report.get("risk_score") or record.get("risk_score") or 0
    evidence_insufficient_ratio = _calc_evidence_insufficient_ratio(claim_reports)

    base_actions: list[ChatAction] = [
        ChatAction(type="command", label="加载到前端上下文", command=f"/load_history {record['id']}"),
        ChatAction(type="command", label="补充证据（/more_evidence）", command="/more_evidence"),
    ]

    if risk_score_val >= 70:
        base_actions.append(ChatAction(type="link", label="生成应对内容", href="/content"))
        base_actions.append(ChatAction(type="command", label="深入分析证据", command=f"/deep_dive {record['id']} evidence"))
    else:
        base_actions.append(ChatAction(type="command", label="查看证据来源", command=f"/deep_dive {record['id']} sources"))
        base_actions.append(ChatAction(type="command", label="对比历史记录", command="/list"))

    if evidence_insufficient_ratio > 0.5:
        base_actions.insert(0, ChatAction(type="command", label="补充检索证据", command="/more_evidence"))

    base_actions.extend([
        ChatAction(type="command", label="改写为短版（/rewrite short）", command="/rewrite short"),
        ChatAction(type="command", label="改写为中性版（/rewrite neutral）", command="/rewrite neutral"),
        ChatAction(type="command", label="改写为亲切版（/rewrite friendly）", command="/rewrite friendly"),
        ChatAction(type="link", label="打开检测结果", href="/result"),
        ChatAction(type="link", label="打开历史记录", href="/history"),
    ])

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=base_actions,
        references=refs,
        meta={"record_id": record["id"], "blocks": blocks},
    )


def run_list(args: ToolListArgs) -> ChatMessage:
    limit = int(args.limit)
    rows = list_history(limit=limit)

    if not rows:
        return ChatMessage(
            role="assistant",
            content=(
                "暂无可用的历史记录。\n\n"
                "你可以先发送 `/analyze <待分析文本>` 生成一次分析；或稍后再试。"
            ),
            actions=[
                ChatAction(type="command", label="示例：开始分析", command="/analyze 网传某事件100%真实，内部人士称..."),
                ChatAction(type="link", label="打开历史记录", href="/history"),
            ],
            references=[],
        )

    lines: list[str] = []
    lines.append(f"最近 {len(rows)} 条历史记录（可用于 /load_history）：")
    for idx, r in enumerate(rows, start=1):
        rid = r.get("id")
        created_at = r.get("created_at")
        preview = r.get("input_preview") or ""
        risk_label = r.get("risk_label")
        risk_score = r.get("risk_score")
        lines.append(f"{idx}. {rid} · {created_at} · {risk_label}({risk_score})")
        if preview:
            lines.append(f"   摘要: {preview}")
    lines.append("")
    lines.append("用法：/load_history <record_id>（例如：/load_history " + str(rows[0].get("id")) + ")")

    actions: list[ChatAction] = [
        ChatAction(type="link", label="打开历史记录", href="/history"),
    ]
    first_id = rows[0].get("id")
    if first_id:
        actions.insert(0, ChatAction(type="command", label="加载最新记录到前端", command=f"/load_history {first_id}"))

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=actions,
        references=[],
    )


def run_analyze_stream(session_id: str, args: ToolAnalyzeArgs) -> Iterator[str]:
    """执行 analyze 工具并通过 SSE 输出 token + 最终 message 事件。"""

    text = args.text.strip()
    if not text:
        msg = ChatMessage(
            role="assistant",
            content="用法：/analyze <待分析文本>。",
            actions=[ChatAction(type="link", label="检测结果", href="/result")],
            references=[],
        )
        event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
        yield f"data: {event.model_dump_json()}\n\n"
        return

    yield f"data: {ChatStreamEvent(type='token', data={'content': '已收到文本，开始分析…\n', 'session_id': session_id}).model_dump_json()}\n\n"

    with llm_slot():
        risk = detect_risk_snapshot(text)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 风险快照：完成（{risk.label}，score={risk.score}）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    with llm_slot():
        claims = orchestrator.run_claims(text, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 主张抽取：完成（{len(claims)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    evidences = orchestrator.run_evidence(text=text, claims=claims, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 联网检索证据：完成（候选 {len(evidences)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    with llm_slot():
        aligned = align_evidences(claims=claims, evidences=evidences, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': f'- 证据聚合与对齐：完成（对齐 {len(aligned)} 条）\n', 'session_id': session_id}).model_dump_json()}\n\n"

    with llm_slot():
        report = orchestrator.run_report(text=text, claims=claims, evidences=aligned, strategy=risk.strategy)
    yield f"data: {ChatStreamEvent(type='token', data={'content': '- 综合报告：完成\n', 'session_id': session_id}).model_dump_json()}\n\n"

    record_id = save_report(
        input_text=text,
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
            description="可在历史记录页查看详情并回放。",
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
            f"- 风险快照: {risk.label}（score={risk.score}）\n"
            f"- 主张数: {len(claims)}\n"
            f"- 对齐证据数: {len(aligned)}\n"
            f"- 报告风险: {report.get('risk_label')}（{report.get('risk_score')}）\n"
            f"- 场景: {report.get('detected_scenario')}\n"
        ),
        actions=[
            ChatAction(type="link", label="打开检测结果", href="/result"),
            ChatAction(type="link", label="打开历史记录", href="/history"),
            ChatAction(type="command", label="加载本次结果到前端", command=f"/load_history {record_id}"),
            ChatAction(type="command", label="为什么这样判定", command=f"/why {record_id}"),
        ],
        references=top_refs,
        meta={"record_id": record_id},
    )

    event = ChatStreamEvent(type="message", data={"session_id": session_id, "message": msg.model_dump()})
    yield f"data: {event.model_dump_json()}\n\n"


def run_compare(args: ToolCompareArgs) -> ChatMessage:
    """对比两条历史记录的分析结果。"""
    record_1 = get_history(args.record_id_1)
    record_2 = get_history(args.record_id_2)

    errors: list[str] = []
    if not record_1:
        errors.append(f"未找到历史记录 1：{args.record_id_1}")
    if not record_2:
        errors.append(f"未找到历史记录 2：{args.record_id_2}")

    if errors:
        return ChatMessage(
            role="assistant",
            content="\n".join(errors),
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    report_1 = record_1.get("report") or {}
    report_2 = record_2.get("report") or {}
    detect_1 = record_1.get("detect_data") or {}
    detect_2 = record_2.get("detect_data") or {}

    lines: list[str] = []
    lines.append("=== 对比分析 ===")
    lines.append("")
    lines.append("【记录 1】")
    lines.append(f"- record_id: {record_1['id']}")
    lines.append(f"- 风险快照: {detect_1.get('label', record_1.get('risk_label'))} (score={detect_1.get('score', record_1.get('risk_score'))})")
    lines.append(f"- 报告风险: {report_1.get('risk_label')} (score={report_1.get('risk_score')})")
    lines.append(f"- 场景: {report_1.get('detected_scenario')}")
    lines.append(f"- 主张数: {len(report_1.get('claim_reports', []))}")
    lines.append("")

    lines.append("【记录 2】")
    lines.append(f"- record_id: {record_2['id']}")
    lines.append(f"- 风险快照: {detect_2.get('label', record_2.get('risk_label'))} (score={detect_2.get('score', record_2.get('risk_score'))})")
    lines.append(f"- 报告风险: {report_2.get('risk_label')} (score={report_2.get('risk_score')})")
    lines.append(f"- 场景: {report_2.get('detected_scenario')}")
    lines.append(f"- 主张数: {len(report_2.get('claim_reports', []))}")
    lines.append("")

    score_diff = (report_1.get("risk_score") or 0) - (report_2.get("risk_score") or 0)
    if score_diff > 10:
        lines.append(f"风险差异：记录 1 风险更高 (差值: +{score_diff})")
    elif score_diff < -10:
        lines.append(f"风险差异：记录 2 风险更高 (差值: {score_diff})")
    else:
        lines.append(f"风险差异：两者接近 (差值: {score_diff})")

    blocks: list[dict[str, Any]] = [
        {
            "kind": "comparison",
            "title": "风险对比",
            "records": [
                {
                    "record_id": record_1["id"],
                    "risk_label": report_1.get("risk_label"),
                    "risk_score": report_1.get("risk_score"),
                    "scenario": report_1.get("detected_scenario"),
                },
                {
                    "record_id": record_2["id"],
                    "risk_label": report_2.get("risk_label"),
                    "risk_score": report_2.get("risk_score"),
                    "scenario": report_2.get("detected_scenario"),
                },
            ],
        }
    ]

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record_1['id']}",
            href="/history",
            description=f"风险: {record_1.get('risk_label')} ({record_1.get('risk_score')})",
        ),
        ChatReference(
            title=f"历史记录：{record_2['id']}",
            href="/history",
            description=f"风险: {record_2.get('risk_label')} ({record_2.get('risk_score')})",
        ),
    ]

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=[
            ChatAction(type="command", label="加载记录 1", command=f"/load_history {record_1['id']}"),
            ChatAction(type="command", label="加载记录 2", command=f"/load_history {record_2['id']}"),
            ChatAction(type="command", label="深入分析记录 1", command=f"/deep_dive {record_1['id']}"),
            ChatAction(type="command", label="深入分析记录 2", command=f"/deep_dive {record_2['id']}"),
            ChatAction(type="link", label="打开历史记录", href="/history"),
        ],
        references=refs,
        meta={"record_id_1": record_1["id"], "record_id_2": record_2["id"], "blocks": blocks},
    )


def run_deep_dive(args: ToolDeepDiveArgs) -> ChatMessage:
    """深入分析某一焦点领域。"""
    record = get_history(args.record_id)
    if not record:
        return ChatMessage(
            role="assistant",
            content=f"未找到历史记录：{args.record_id}",
            actions=[ChatAction(type="link", label="打开历史记录", href="/history")],
            references=[],
        )

    report = record.get("report") or {}
    detect_data = record.get("detect_data") or {}
    claim_reports = report.get("claim_reports") or []
    focus = args.focus or "general"

    lines: list[str] = []
    lines.append(f"=== 深入分析 ({focus}) ===")
    lines.append(f"record_id: {record['id']}")
    lines.append("")

    blocks: list[dict[str, Any]] = []

    if focus in ("general", "evidence"):
        lines.append("【证据深度分析】")
        lines.append(f"- 对齐证据总数: {sum(len(cr.get('evidences', [])) for cr in claim_reports)}")

        stance_counts: dict[str, int] = {"support": 0, "oppose": 0, "insufficient_evidence": 0}
        source_urls: list[str] = []

        for cr in claim_reports:
            for ev in cr.get("evidences", []):
                stance = ev.get("stance", "insufficient_evidence")
                if stance in stance_counts:
                    stance_counts[stance] += 1
                url = ev.get("url")
                if url and url.startswith("http"):
                    source_urls.append(url)

        lines.append(f"- 证据立场分布:")
        lines.append(f"  - 支持: {stance_counts['support']}")
        lines.append(f"  - 反对: {stance_counts['oppose']}")
        lines.append(f"  - 证据不足: {stance_counts['insufficient_evidence']}")
        lines.append(f"- 来源链接数: {len(set(source_urls))}")
        lines.append("")

        blocks.append({
            "kind": "evidence_stats",
            "title": "证据统计",
            "stance_distribution": stance_counts,
            "unique_sources": len(set(source_urls)),
        })

    if focus in ("general", "claims") and claim_reports:
        lines.append("【主张分析】")
        target_claims = claim_reports
        if args.claim_index is not None and 0 <= args.claim_index < len(claim_reports):
            target_claims = [claim_reports[args.claim_index]]
            lines.append(f"- 聚焦主张 #{args.claim_index}")

        for idx, cr in enumerate(target_claims):
            claim_text = (cr.get("claim") or {}).get("claim_text", "")[:80]
            verdict = cr.get("verdict", "未知")
            evidences = cr.get("evidences", [])
            lines.append(f"  主张 {args.claim_index if args.claim_index is not None else idx}: {claim_text}…")
            lines.append(f"    - 结论: {verdict}")
            lines.append(f"    - 证据数: {len(evidences)}")
        lines.append("")

        blocks.append({
            "kind": "claims_analysis",
            "title": "主张分析",
            "focus_index": args.claim_index,
            "total_claims": len(claim_reports),
        })

    if focus in ("general", "timeline"):
        lines.append("【时间线】")
        lines.append(f"- 创建时间: {record.get('created_at')}")
        lines.append(f"- 更新时间: {record.get('updated_at')}")
        if detect_data.get("reasons"):
            lines.append("- 风险快照触发原因:")
            for r in detect_data.get("reasons", [])[:3]:
                lines.append(f"  - {r}")
        lines.append("")

    if focus in ("general", "sources"):
        lines.append("【来源追溯】")
        seen_urls: set[str] = set()
        for cr in claim_reports:
            for ev in cr.get("evidences", []):
                url = ev.get("url")
                if url and url.startswith("http") and url not in seen_urls:
                    seen_urls.add(url)
                    title = ev.get("title", url)[:60]
                    lines.append(f"  - [{title}]({url})")
                    if len(seen_urls) >= 10:
                        break
            if len(seen_urls) >= 10:
                break
        lines.append("")

    refs: list[ChatReference] = [
        ChatReference(
            title=f"历史记录：{record['id']}",
            href="/history",
            description=f"风险: {record.get('risk_label')} ({record.get('risk_score')})",
        )
    ]

    return ChatMessage(
        role="assistant",
        content="\n".join(lines),
        actions=[
            ChatAction(type="command", label="为什么这样判定", command=f"/why {record['id']}"),
            ChatAction(type="command", label="补充证据", command="/more_evidence"),
            ChatAction(type="command", label="深入证据", command=f"/deep_dive {record['id']} evidence"),
            ChatAction(type="command", label="深入主张", command=f"/deep_dive {record['id']} claims"),
            ChatAction(type="link", label="打开检测结果", href="/result"),
        ],
        references=refs,
        meta={"record_id": record["id"], "focus": focus, "blocks": blocks},
    )
