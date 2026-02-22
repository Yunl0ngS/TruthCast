from app.orchestrator import orchestrator


def test_orchestrator_report_smoke() -> None:
    report = orchestrator.run_report(text="Shocking internal source says this is 100% true.")
    assert "risk_score" in report
    assert "claim_reports" in report


def test_orchestrator_simulation_smoke() -> None:
    result = orchestrator.run_simulation(
        text="Rumor is spreading fast.",
        time_window_hours=24,
        platform="general",
        comments=[],
    )
    assert hasattr(result, "narratives")
    assert len(result.narratives) >= 2
