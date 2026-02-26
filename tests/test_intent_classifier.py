"""Tests for intent_classifier module."""

import pytest

from app.services.intent_classifier import (
    IntentName,
    build_suggested_actions,
    classify_intent,
)


@pytest.mark.parametrize(
    "text",
    [
        "只提取主张：这条新闻说某地停课三天",
        "只帮我提取主张：网传明天全城停课",
        "仅提取主张，不要做别的",
        "先提取主张然后我再看",
        "帮我抽取主张",
        "提取主张列表",
        "做主张抽取",
        "只要主张结果",
        "仅要主张",
        "列出主张",
        "给我主张",
    ],
)
def test_classify_intent_claims_only_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "claims_only"


@pytest.mark.parametrize(
    "text",
    [
        "只检索证据",
        "仅检索证据",
        "先查证据",
        "补充检索证据",
        "证据检索一下",
        "查证据链接",
        "联网查证据",
        "找来源证据",
        "先搜证据",
        "只找证据",
    ],
)
def test_classify_intent_evidence_only_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "evidence_only"


@pytest.mark.parametrize(
    "text",
    [
        "只做对齐",
        "仅做对齐",
        "证据对齐",
        "先对齐证据",
        "做下对齐",
        "对齐主张和证据",
        "只要对齐结果",
        "仅要对齐结果",
        "执行 align",
        "跑对齐",
    ],
)
def test_classify_intent_align_only_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "align_only"


@pytest.mark.parametrize(
    "text",
    [
        "只生成报告",
        "仅生成报告",
        "报告详情",
        "生成综合报告",
        "输出报告",
        "只要报告",
        "仅要报告",
        "给我报告",
        "先出报告",
        "报告阶段先做",
    ],
)
def test_classify_intent_report_only_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "report_only"


@pytest.mark.parametrize(
    "text",
    [
        "舆情预演",
        "舆论预演",
        "预演传播路径",
        "做个预演",
        "模拟舆情",
        "模拟传播",
        "风险传播模拟",
        "跑模拟",
        "生成预演结果",
        "情绪分布预测",
    ],
)
def test_classify_intent_simulate_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "simulate"


@pytest.mark.parametrize(
    "text",
    [
        "生成应对内容",
        "写澄清稿",
        "应对内容给我",
        "做一份澄清稿",
        "生成声明",
        "写声明",
        "公关稿写一下",
        "回应内容准备一下",
        "生成一份应对文案",
        "写个对外回应",
    ],
)
def test_classify_intent_content_samples(text: str):
    intent, _ = classify_intent(text)
    assert intent == "content"


@pytest.mark.parametrize(
    "text,expected_intent",
    [
        ("为什么判定高风险？", "why"),
        ("为什么风险这么高", "why"),
        ("怎么得出的结论", "why"),
        ("判定依据是什么", "why"),
        ("解释一下判定原因", "why"),
        ("对比上次结果", "compare"),
        ("比较两条记录", "compare"),
        ("和之前对比一下", "compare"),
        ("深入分析证据", "deep_dive"),
        ("详细看看证据来源", "deep_dive"),
        ("生成应对内容", "content"),
        ("写一份澄清稿", "content"),
        ("补充一些证据", "more_evidence"),
        ("更多证据", "more_evidence"),
        ("历史记录", "list"),
        ("查看历史", "list"),
        ("怎么用", "help"),
        ("帮助", "help"),
    ],
)
def test_classify_intent_natural_language(text: str, expected_intent: IntentName):
    """Test natural language intent classification."""
    intent, args = classify_intent(text)
    assert intent == expected_intent


@pytest.mark.parametrize(
    "text,expected_intent,expected_args",
    [
        ("/why rec_123", "why", {"record_id": "rec_123"}),
        ("/explain rec_456", "why", {"record_id": "rec_456"}),
        ("/compare rec_1 rec_2", "compare", {"record_id_1": "rec_1", "record_id_2": "rec_2"}),
        ("/deep_dive rec_123 evidence", "deep_dive", {"record_id": "rec_123", "focus": "evidence", "claim_index": None}),
        ("/deep_dive rec_123 claims 2", "deep_dive", {"record_id": "rec_123", "focus": "claims", "claim_index": 2}),
        ("/list 20", "list", {"limit": 20}),
        ("/history", "list", {"limit": 10}),
        ("/more_evidence", "more_evidence", {}),
        ("/more", "more_evidence", {}),
        ("/analyze 这是一段待分析的文本", "analyze", {"text": "这是一段待分析的文本"}),
        ("/help", "help", {}),
        ("/rewrite short", "rewrite", {"style": "short"}),
        ("/rewrite friendly", "rewrite", {"style": "friendly"}),
        ("/load_history rec_123", "load_history", {"record_id": "rec_123"}),
    ],
)
def test_classify_intent_commands(text: str, expected_intent: IntentName, expected_args: dict[str, object]):
    """Test command-style intent classification."""
    intent, args = classify_intent(text)
    assert intent == expected_intent
    for key, value in expected_args.items():
        assert args.get(key) == value


def test_classify_intent_empty():
    """Test empty input returns help."""
    intent, args = classify_intent("")
    assert intent == "help"
    assert args == {}


def test_classify_intent_unknown():
    """Test unknown input returns unknown intent."""
    intent, args = classify_intent("这是一些随机的文字没有特定意图")
    assert intent == "unknown"


def test_classify_intent_with_session_meta():
    """Test command parsing with session meta for record_id fallback."""
    from app.services.intent_classifier import _parse_command_intent

    intent, args = _parse_command_intent("/why")
    assert intent == "why"
    assert args.get("record_id") == ""

    intent, args = _parse_command_intent("/deep_dive")
    assert intent == "deep_dive"
    assert args.get("record_id") == ""


def test_build_suggested_actions_why_high_risk():
    """Test dynamic actions for why intent with high risk."""
    actions = build_suggested_actions(
        "why",
        record_id="rec_123",
        risk_score=80,
        evidence_insufficient_ratio=0.2,
    )
    assert len(actions) >= 1
    action_labels = [a.get("label") for a in actions]
    assert any("深入分析证据" in str(label) for label in action_labels)
    assert any("生成应对内容" in str(label) for label in action_labels)


def test_build_suggested_actions_why_low_risk():
    """Test dynamic actions for why intent with low risk."""
    actions = build_suggested_actions(
        "why",
        record_id="rec_123",
        risk_score=50,
        evidence_insufficient_ratio=0.2,
    )
    action_labels = [a.get("label") for a in actions]
    assert any("查看证据来源" in str(label) for label in action_labels)


def test_build_suggested_actions_evidence_insufficient():
    """Test dynamic actions when evidence is insufficient."""
    actions = build_suggested_actions(
        "why",
        record_id="rec_123",
        risk_score=50,
        evidence_insufficient_ratio=0.6,
    )
    assert len(actions) >= 1
    first_action = actions[0]
    assert "补充检索证据" in first_action.get("label", "")


def test_build_suggested_actions_deep_dive():
    """Test dynamic actions for deep_dive intent."""
    actions = build_suggested_actions(
        "deep_dive",
        record_id="rec_123",
    )
    action_labels = [a.get("label") for a in actions]
    assert any("为什么这样判定" in str(label) for label in action_labels)
    assert any("深入其他焦点" in str(label) for label in action_labels)


def test_build_suggested_actions_compare():
    """Test dynamic actions for compare intent."""
    actions = build_suggested_actions("compare")
    action_labels = [a.get("label") for a in actions]
    assert any("列出最近记录" in str(label) for label in action_labels)


def test_build_suggested_actions_list():
    """Test dynamic actions for list intent."""
    actions = build_suggested_actions("list")
    action_labels = [a.get("label") for a in actions]
    assert any("历史记录" in str(label) for label in action_labels)


def test_build_suggested_actions_more_evidence():
    """Test dynamic actions for more_evidence intent."""
    actions = build_suggested_actions(
        "more_evidence",
        record_id="rec_123",
    )
    action_labels = [a.get("label") for a in actions]
    assert any("重试证据检索" in str(label) for label in action_labels)


def test_intent_patterns_coverage():
    """Test that INTENT_PATTERNS are valid regex patterns."""
    import re
    from app.services.intent_classifier import INTENT_PATTERNS

    for intent, patterns in INTENT_PATTERNS.items():
        for pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as e:
                pytest.fail(f"Invalid regex pattern for {intent}: {pattern} - {e}")


def test_llm_fallback_enabled_for_unknown(monkeypatch: pytest.MonkeyPatch):
    from app.services import intent_classifier as ic

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"intent":"claims_only","args":{"text":"测试文本"}}'}}
                ]
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            return _Resp()

    monkeypatch.setenv("TRUTHCAST_CHAT_INTENT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "test-key")
    monkeypatch.setattr(ic.httpx, "Client", _Client)

    intent, args = classify_intent("这句话本身很模糊但请帮我处理")
    assert intent == "claims_only"
    assert args.get("text") == "测试文本"


def test_llm_fallback_invalid_tool_returns_unknown(monkeypatch: pytest.MonkeyPatch):
    from app.services import intent_classifier as ic

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"tool":"drop_database","args":{"x":1}}'}}
                ]
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            return _Resp()

    monkeypatch.setenv("TRUTHCAST_CHAT_INTENT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "test-key")
    monkeypatch.setattr(ic.httpx, "Client", _Client)

    intent, _ = classify_intent("无明显规则意图的句子")
    assert intent == "unknown"


def test_llm_fallback_still_constrained_by_guardrails(monkeypatch: pytest.MonkeyPatch):
    from app.core.guardrails import validate_tool_call
    from app.services import intent_classifier as ic
    from app.services.chat_orchestrator import parse_tool

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [
                    {"message": {"content": '{"intent":"compare","args":{"record_id_1":""}}'}}
                ]
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers, json):
            return _Resp()

    monkeypatch.setenv("TRUTHCAST_CHAT_INTENT_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "test-key")
    monkeypatch.setattr(ic.httpx, "Client", _Client)

    tool, args = parse_tool("这句无法被规则识别")
    assert tool == "compare"
    validation = validate_tool_call(tool, args)
    assert validation.is_valid is False


@pytest.mark.parametrize(
    "text,expected_tool",
    [
        ("只提取主张：今天有新政策", "claims_only"),
        ("只检索证据，不做报告", "evidence_only"),
        ("证据对齐先做", "align_only"),
        ("只生成报告详情", "report_only"),
        ("帮我做舆情预演", "simulate"),
        ("写一份澄清稿", "content_generate"),
    ],
)
def test_parse_tool_routes_new_intents(text: str, expected_tool: str):
    from app.services.chat_orchestrator import parse_tool

    tool, _ = parse_tool(text)
    assert tool == expected_tool


def test_parse_tool_unknown_returns_clarify_payload():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("今天的天气真不错")
    assert tool == "help"
    assert args.get("clarify") is True


def test_parse_tool_natural_language_analyze_routes_directly():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("帮我分析这段新闻内容")
    assert tool == "analyze"
    assert "分析" in str(args.get("text") or "")


def test_classify_intent_evidence_execute_beats_more_evidence():
    from app.services.intent_classifier import classify_intent

    intent, _ = classify_intent("帮我检索证据：网传某地停课，是否属实")
    assert intent == "evidence_only"


def test_parse_tool_evidence_long_payload_does_not_fall_into_more_evidence():
    from app.services.chat_orchestrator import parse_tool

    text = "帮我检索证据：四川广元一名男子失联后被找到，救援队称其已离世，警方已介入调查。"
    tool, args = parse_tool(text)
    assert tool == "evidence_only"
    assert "四川广元" in str(args.get("text") or "")


def test_parse_tool_content_alias_with_flags():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("/content style=friendly detail=full force=true reuse_only=false")
    assert tool == "content_generate"
    assert args.get("style") == "friendly"
    assert args.get("detail") == "full"
    assert args.get("force") is True
    assert args.get("reuse_only") is False


def test_parse_tool_content_show_routes_to_show_operation():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("/content_show faq 1-3")
    assert tool == "content_generate"
    assert args.get("operation") == "show"
    assert args.get("section") == "faq"


def test_parse_tool_content_generate_natural_language_without_payload_does_not_set_text():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("继续生成应对内容")
    assert tool == "content_generate"
    assert (args.get("text") or "") == ""


def test_parse_tool_content_generate_natural_language_with_payload_sets_text():
    from app.services.chat_orchestrator import parse_tool

    tool, args = parse_tool("帮我生成应对内容：这是一段需要生成应对内容的新闻正文，长度足够触发正文提取。")
    assert tool == "content_generate"
    assert "新闻正文" in str(args.get("text") or "")
