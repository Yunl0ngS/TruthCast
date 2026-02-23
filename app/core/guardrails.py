from __future__ import annotations

import re
import html
from typing import Any

from pydantic import BaseModel, Field, field_validator

DANGEROUS_PATTERNS = [
    re.compile(r"<\s*script", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"<\s*iframe", re.IGNORECASE),
    re.compile(r"<\s*object", re.IGNORECASE),
    re.compile(r"<\s*embed", re.IGNORECASE),
    re.compile(r"<\s*form", re.IGNORECASE),
]

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+.*?instructions?", re.IGNORECASE),
    re.compile(r"forget\s+.*?instructions?", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"disregard\s+(all|any)\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\s*\|\s*.*?\s*\|\s*>"),
    re.compile(r"\[?\s*system\s*\]?", re.IGNORECASE),
]

MAX_TEXT_LENGTH = 12000
MAX_RECORD_ID_LENGTH = 128
MAX_STYLE_LENGTH = 32
MAX_LIMIT_VALUE = 50
MIN_LIMIT_VALUE = 1

ALLOWED_TOOLS = {
    "analyze",
    "load_history",
    "why",
    "list",
    "more_evidence",
    "rewrite",
    "help",
    "compare",
    "deep_dive",
    "export",
}


class SanitizedInput(BaseModel):
    original: str
    sanitized: str
    was_modified: bool
    warnings: list[str] = Field(default_factory=list)


def sanitize_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> SanitizedInput:
    if not text:
        return SanitizedInput(original=text, sanitized=text, was_modified=False)

    warnings: list[str] = []
    sanitized = text

    for pattern in DANGEROUS_PATTERNS:
        if pattern.search(sanitized):
            sanitized = pattern.sub("[已移除危险内容]", sanitized)
            warnings.append("检测到潜在危险内容已清理")

    sanitized = html.escape(sanitized)

    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            warnings.append("检测到疑似提示注入模式，已标记")
            break

    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length]
        warnings.append(f"文本已截断至 {max_length} 字符")

    was_modified = sanitized != text or len(warnings) > 0

    return SanitizedInput(
        original=text,
        sanitized=sanitized,
        was_modified=was_modified,
        warnings=warnings,
    )


def sanitize_record_id(record_id: str) -> str:
    if not record_id:
        return ""
    sanitized = re.sub(r"[^a-zA-Z0-9_\-:]", "", record_id[:MAX_RECORD_ID_LENGTH])
    return sanitized


def sanitize_style(style: str) -> str:
    if not style:
        return "short"
    allowed_styles = {"short", "neutral", "friendly", "formal", "casual"}
    normalized = style.strip().lower()[:MAX_STYLE_LENGTH]
    return normalized if normalized in allowed_styles else "short"


def sanitize_limit(limit: int) -> int:
    return max(MIN_LIMIT_VALUE, min(limit, MAX_LIMIT_VALUE))


class ToolCallValidator(BaseModel):
    tool_name: str
    args: dict[str, Any]
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def validate_analyze_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    text = args.get("text", "")
    if not text:
        errors.append("缺少必需参数: text")
    else:
        result = sanitize_text(text)
        validated["text"] = result.sanitized
        if result.was_modified:
            warnings.extend(result.warnings)

    return validated, errors, warnings


def validate_load_history_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    record_id = args.get("record_id", "")
    if not record_id:
        errors.append("缺少必需参数: record_id")
    else:
        validated["record_id"] = sanitize_record_id(record_id)
        if validated["record_id"] != record_id:
            warnings.append("record_id 已被清理")

    return validated, errors, warnings


def validate_why_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    return validate_load_history_args(args)


def validate_list_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    limit = args.get("limit", 10)
    try:
        limit_int = int(limit)
        validated["limit"] = sanitize_limit(limit_int)
        if validated["limit"] != limit_int:
            warnings.append(f"limit 已调整为 {validated['limit']}")
    except (TypeError, ValueError):
        validated["limit"] = 10
        warnings.append("limit 参数无效，已使用默认值 10")

    return validated, errors, warnings


def validate_more_evidence_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    record_id = args.get("record_id", "")
    if record_id:
        validated["record_id"] = sanitize_record_id(record_id)
        if validated["record_id"] != record_id:
            warnings.append("record_id 已被清理")
    else:
        validated["record_id"] = ""

    return validated, errors, warnings


def validate_rewrite_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    record_id = args.get("record_id", "")
    if record_id:
        validated["record_id"] = sanitize_record_id(record_id)
        if validated["record_id"] != record_id:
            warnings.append("record_id 已被清理")
    else:
        validated["record_id"] = ""

    style = args.get("style", "short")
    validated["style"] = sanitize_style(style)
    if validated["style"] != style:
        warnings.append(f"style 已调整为 {validated['style']}")

    return validated, errors, warnings


def validate_compare_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    record_id_1 = args.get("record_id_1", "") or args.get("record_id", "")
    record_id_2 = args.get("record_id_2", "") or args.get("compare_with", "")

    if not record_id_1:
        errors.append("缺少参数: record_id_1")
    else:
        validated["record_id_1"] = sanitize_record_id(record_id_1)

    if not record_id_2:
        errors.append("缺少参数: record_id_2")
    else:
        validated["record_id_2"] = sanitize_record_id(record_id_2)

    return validated, errors, warnings


def validate_deep_dive_args(args: dict[str, Any]) -> tuple[dict[str, Any], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    validated: dict[str, Any] = {}

    record_id = args.get("record_id", "")
    if not record_id:
        errors.append("缺少必需参数: record_id")
    else:
        validated["record_id"] = sanitize_record_id(record_id)

    focus = args.get("focus", "general")
    allowed_focus = {"general", "evidence", "claims", "timeline", "sources"}
    validated["focus"] = focus if focus in allowed_focus else "general"

    claim_index = args.get("claim_index")
    if claim_index is not None:
        try:
            validated["claim_index"] = max(0, int(claim_index))
        except (TypeError, ValueError):
            warnings.append("claim_index 参数无效，已忽略")

    return validated, errors, warnings


VALIDATORS = {
    "analyze": validate_analyze_args,
    "load_history": validate_load_history_args,
    "why": validate_why_args,
    "list": validate_list_args,
    "more_evidence": validate_more_evidence_args,
    "rewrite": validate_rewrite_args,
    "compare": validate_compare_args,
    "deep_dive": validate_deep_dive_args,
}


def validate_tool_call(tool_name: str, args: dict[str, Any]) -> ToolCallValidator:
    errors: list[str] = []
    warnings: list[str] = []
    validated_args: dict[str, Any] = {}

    if tool_name not in ALLOWED_TOOLS:
        return ToolCallValidator(
            tool_name=tool_name,
            args=args,
            is_valid=False,
            errors=[f"工具 '{tool_name}' 不在白名单中"],
            warnings=[],
        )

    validator = VALIDATORS.get(tool_name)
    if validator:
        validated_args, errors, warnings = validator(args)
    else:
        validated_args = args

    return ToolCallValidator(
        tool_name=tool_name,
        args=validated_args,
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


def build_guardrails_warning_message(warnings: list[str]) -> str:
    if not warnings:
        return ""
    return "安全护栏提示：\n- " + "\n- ".join(warnings) + "\n"
