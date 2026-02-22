from app.services import opinion_simulation
from app.schemas.detect import ClaimItem, EvidenceItem, NarrativeItem, ReportResponse


def test_simulate_opinion_rule_fallback() -> None:
    result = opinion_simulation.simulate_opinion_with_llm(
        text="这是一条震惊的消息，必转！",
        time_window_hours=24,
        platform="weibo",
        comments=["官方通报来了"],
    )

    assert "emotion_distribution" in result.model_dump()
    assert "stance_distribution" in result.model_dump()
    assert len(result.narratives) >= 1
    assert len(result.flashpoints) >= 1
    assert result.suggestion != ""


def test_simulate_opinion_with_context() -> None:
    claims = [
        ClaimItem(
            claim_id="c1",
            claim_text="某地发生重大事件",
            source_sentence="某地发生重大事件",
        )
    ]
    evidences = [
        EvidenceItem(
            evidence_id="e1",
            claim_id="c1",
            title="官方辟谣",
            source="news.cctv.com",
            url="https://news.cctv.com/example",
            published_at="2026-02-10",
            summary="经核实为不实信息",
            stance="refute",
            source_weight=0.9,
        )
    ]
    report = ReportResponse(
        risk_score=75,
        risk_level="high",
        risk_label="高风险",
        detected_scenario="governance",
        evidence_domains=["governance"],
        summary="该信息存在较高风险",
        suspicious_points=["来源不明", "缺乏证据支持"],
        claim_reports=[],
    )

    result = opinion_simulation.simulate_opinion_with_llm(
        text="某地发生重大事件",
        claims=claims,
        evidences=evidences,
        report=report,
        time_window_hours=48,
        platform="weixin",
    )

    assert result.emotion_distribution is not None
    assert result.stance_distribution is not None
    assert len(result.narratives) >= 2


def test_simulate_llm_disabled_uses_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_SIMULATION_LLM_ENABLED", "false")

    result = opinion_simulation.simulate_opinion_with_llm(
        text="普通新闻内容",
        time_window_hours=12,
        platform="douyin",
    )

    assert result.emotion_distribution is not None
    assert result.stance_distribution is not None


def test_fallback_emotion_stance_trigger_words() -> None:
    emotion_result = opinion_simulation._fallback_emotion_stance(
        text="震惊！惊天大秘密曝光！",
        report=None,
        comments=[],
    )

    assert emotion_result["emotion_distribution"]["anger"] >= 0.2
    assert emotion_result["emotion_distribution"]["surprise"] >= 0.2


def test_fallback_narratives() -> None:
    report = ReportResponse(
        risk_score=80,
        risk_level="high",
        risk_label="高风险",
        detected_scenario="health",
        evidence_domains=["health"],
        summary="高风险内容",
        suspicious_points=[],
        claim_reports=[],
    )

    narratives = opinion_simulation._fallback_narratives(report, "weibo")

    assert len(narratives) == 3
    assert all(isinstance(n, NarrativeItem) for n in narratives)
    assert narratives[0].stance == "doubt"
    assert narratives[0].probability >= 0.3


def test_fallback_flashpoints() -> None:
    flashpoints, timeline = opinion_simulation._fallback_flashpoints(
        platform="weibo",
        time_window_hours=48,
    )

    assert len(flashpoints) == 3
    assert len(timeline) == 3
    assert timeline[0]["hour"] == 1


def test_fallback_suggestion_high_risk() -> None:
    report = ReportResponse(
        risk_score=85,
        risk_level="high",
        risk_label="高风险",
        detected_scenario="governance",
        evidence_domains=["governance"],
        summary="高风险",
        suspicious_points=[],
        claim_reports=[],
    )

    suggestion = opinion_simulation._fallback_suggestion(report)
    assert "立即" in suggestion.summary or "官方" in suggestion.summary


def test_fallback_suggestion_low_risk() -> None:
    report = ReportResponse(
        risk_score=20,
        risk_level="low",
        risk_label="低风险",
        detected_scenario="technology",
        evidence_domains=["technology"],
        summary="低风险",
        suspicious_points=[],
        claim_reports=[],
    )

    suggestion = opinion_simulation._fallback_suggestion(report)
    assert "监测" in suggestion.summary or "透明" in suggestion.summary
