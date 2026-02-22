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


def test_risk_snapshot_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("TRUTHCAST_LLM_API_KEY", "dummy")
    monkeypatch.setattr(risk_snapshot, "_detect_with_llm", lambda text: None)

    result = risk_snapshot.detect_risk_snapshot(
        "Shocking internal source says this is 100% true."
    )
    assert result.label in {"credible", "suspicious", "high_risk"}
