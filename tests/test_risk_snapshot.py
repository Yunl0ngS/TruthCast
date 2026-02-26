from app.services import risk_snapshot


def test_risk_snapshot_llm_path(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")

    monkeypatch.setattr(
        risk_snapshot,
        "_detect_with_llm",
        lambda text: risk_snapshot.ScoreResult(
            label="likely_misinformation",
            score=22,
            confidence=0.91,
            reasons=["检测到明显误导话术。"],
        ),
    )

    result = risk_snapshot.detect_risk_snapshot("some text")
    assert result.label == "likely_misinformation"
    assert result.score == 22
    assert result.strategy is not None
    assert result.strategy.complexity_level in {"simple", "medium", "complex"}


def test_risk_snapshot_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(risk_snapshot, "_detect_with_llm", lambda text: None)

    result = risk_snapshot.detect_risk_snapshot(
        "Shocking internal source says this is 100% true."
    )
    assert result.label in {"credible", "suspicious", "high_risk"}
    assert result.strategy is not None


def test_risk_snapshot_complexity_runs_before_risk(monkeypatch) -> None:
    order: list[str] = []

    def _fake_complexity(text: str):
        order.append("complexity")
        return ("medium", "复杂度测试", 5, True, 0.9, "news", "新闻文本")

    def _fake_llm(text: str):
        order.append("risk")
        return risk_snapshot.ScoreResult(
            label="suspicious",
            score=55,
            confidence=0.66,
            reasons=["测试原因"],
            strategy=None,
        )

    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(risk_snapshot, "analyze_text_meta", _fake_complexity)
    monkeypatch.setattr(risk_snapshot, "_detect_with_llm", _fake_llm)

    result = risk_snapshot.detect_risk_snapshot("test text")
    assert order == ["complexity", "risk"]
    assert result.strategy is not None
    assert result.strategy.max_claims == 5
    assert result.strategy.complexity_reason == "复杂度测试"


def test_risk_snapshot_news_gate_blocks_before_risk_llm(monkeypatch) -> None:
    monkeypatch.setattr(
        risk_snapshot,
        "analyze_text_meta",
        lambda text: ("simple", "非新闻文本", 3, False, 0.91, "chat", "闲聊语句"),
    )

    def _should_not_call(text: str):
        raise AssertionError("news gate 阻断后不应调用风险快照LLM")

    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(risk_snapshot, "_detect_with_llm", _should_not_call)

    result = risk_snapshot.detect_risk_snapshot("你好呀，今天心情不错", enable_news_gate=True)
    assert result.strategy is not None
    assert result.strategy.is_news is False
    assert result.label == "needs_context"


def test_risk_snapshot_force_bypasses_news_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        risk_snapshot,
        "analyze_text_meta",
        lambda text: ("simple", "非新闻文本", 3, False, 0.91, "chat", "闲聊语句"),
    )

    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(
        risk_snapshot,
        "_detect_with_llm",
        lambda text: risk_snapshot.ScoreResult(
            label="suspicious",
            score=54,
            confidence=0.7,
            reasons=["强制检测"],
            strategy=None,
        ),
    )

    result = risk_snapshot.detect_risk_snapshot("你好呀，今天心情不错", force=True, enable_news_gate=True)
    assert result.strategy is not None
    assert result.strategy.is_news is False
    assert result.label == "suspicious"
