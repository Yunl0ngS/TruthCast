"""Tests for intent_classifier module."""

import pytest

from app.services.intent_classifier import (
    IntentName,
    build_suggested_actions,
    classify_intent,
)


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
def test_classify_intent_commands(text: str, expected_intent: IntentName, expected_args: dict):
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
    assert any("深入分析证据" in label for label in action_labels)
    assert any("生成应对内容" in label for label in action_labels)


def test_build_suggested_actions_why_low_risk():
    """Test dynamic actions for why intent with low risk."""
    actions = build_suggested_actions(
        "why",
        record_id="rec_123",
        risk_score=50,
        evidence_insufficient_ratio=0.2,
    )
    action_labels = [a.get("label") for a in actions]
    assert any("查看证据来源" in label for label in action_labels)


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
    assert any("为什么这样判定" in label for label in action_labels)
    assert any("深入其他焦点" in label for label in action_labels)


def test_build_suggested_actions_compare():
    """Test dynamic actions for compare intent."""
    actions = build_suggested_actions("compare")
    action_labels = [a.get("label") for a in actions]
    assert any("列出最近记录" in label for label in action_labels)


def test_build_suggested_actions_list():
    """Test dynamic actions for list intent."""
    actions = build_suggested_actions("list")
    action_labels = [a.get("label") for a in actions]
    assert any("历史记录" in label for label in action_labels)


def test_build_suggested_actions_more_evidence():
    """Test dynamic actions for more_evidence intent."""
    actions = build_suggested_actions(
        "more_evidence",
        record_id="rec_123",
    )
    action_labels = [a.get("label") for a in actions]
    assert any("重试证据检索" in label for label in action_labels)


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
