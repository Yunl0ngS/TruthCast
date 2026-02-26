"""SSE end-to-end acceptance checks (no manual inspection required).

Runs against FastAPI TestClient and asserts stage order + done event for:
- claims-only
- evidence-only
- report-only
- simulate
"""

from __future__ import annotations

import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from fastapi.testclient import TestClient

# Ensure repository root is importable when running as script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app


def _parse_sse(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            events.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return events


def _stream_text(client: TestClient, session_id: str, text: str) -> str:
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": text, "context": None},
    ) as resp:
        assert resp.status_code == 200, f"stream failed: {resp.status_code}"
        return "".join(list(resp.iter_text()))


def _assert_stage_order(events: list[dict[str, Any]], stage_name: str) -> None:
    status_seq: list[str] = []
    for event in events:
        if event.get("type") != "stage":
            continue
        data = event.get("data") or {}
        if data.get("stage") == stage_name:
            status_seq.append(str(data.get("status") or ""))
    assert "running" in status_seq, f"missing running stage for {stage_name}"
    assert "done" in status_seq, f"missing done stage for {stage_name}"
    assert status_seq.index("running") < status_seq.index("done"), f"invalid stage order for {stage_name}: {status_seq}"


def _assert_done_event(events: list[dict[str, Any]]) -> None:
    assert any(event.get("type") == "done" for event in events), "missing done event"


def main() -> None:
    client = TestClient(app)

    create_resp = client.post("/chat/sessions", json={})
    if create_resp.status_code != 200:
        raise AssertionError(f"create session failed: {create_resp.status_code} {create_resp.text}")
    session_id = create_resp.json()["session_id"]

    # 1) claims-only
    raw_claims = _stream_text(client, session_id, "/claims_only 网传某地停课三天，官方尚未通报")
    claims_events = _parse_sse(raw_claims)
    _assert_stage_order(claims_events, "claims_only")
    _assert_done_event(claims_events)

    with ExitStack() as stack:
        # 2) evidence-only (avoid external retrieval dependencies)
        stack.enter_context(
            patch(
                "app.api.routes_chat.orchestrator.run_evidence",
                return_value=[],
            )
        )

        raw_evidence = _stream_text(client, session_id, "/evidence_only 网传某地停课三天，官方尚未通报")
        evidence_events = _parse_sse(raw_evidence)
        _assert_stage_order(evidence_events, "evidence_only")
        _assert_done_event(evidence_events)

    with ExitStack() as stack:
        # 3) report-only (reuse aligned payload + deterministic report)
        stack.enter_context(
            patch(
                "app.api.routes_chat.get_phase_payload",
                side_effect=lambda task_id, phase: (
                    {
                        "claims": [
                            {
                                "claim_id": "c1",
                                "claim_text": "网传某地停课三天",
                                "source_sentence": "网传某地停课三天",
                            }
                        ],
                        "evidences": [
                            {
                                "evidence_id": "e1",
                                "claim_id": "c1",
                                "title": "权威辟谣",
                                "summary": "官方尚未发布停课通知",
                                "url": "https://example.com/e1",
                                "source": "example",
                                "published_at": "2026-02-25",
                                "stance": "oppose",
                                "source_weight": 0.8,
                                "alignment_confidence": 0.88,
                                "alignment_rationale": "权威渠道与网传说法相反",
                            }
                        ],
                    }
                    if phase in {"evidence_align", "align"}
                    else {}
                ),
            )
        )
        stack.enter_context(
            patch(
                "app.api.routes_chat.orchestrator.run_report",
                return_value={
                    "risk_score": 82,
                    "risk_label": "suspicious",
                    "risk_level": "high",
                    "summary": "存在明显矛盾证据",
                    "suspicious_points": ["来源不明", "与官方口径冲突"],
                    "detected_scenario": "education",
                    "evidence_domains": ["education", "governance"],
                    "claim_reports": [],
                },
            )
        )

        raw_report = _stream_text(client, session_id, "/report_only")
        report_events = _parse_sse(raw_report)
        _assert_stage_order(report_events, "report_only")
        _assert_done_event(report_events)

    with ExitStack() as stack:
        # 4) simulate (deterministic staged stream)
        stack.enter_context(
            patch(
                "app.api.routes_chat.get_phase_payload",
                side_effect=lambda task_id, phase: (
                    {
                        "report": {
                            "risk_score": 68,
                            "risk_level": "high",
                            "risk_label": "suspicious",
                            "detected_scenario": "general",
                            "evidence_domains": ["media"],
                            "summary": "存在争议",
                            "suspicious_points": ["来源不明"],
                            "claim_reports": [],
                        }
                    }
                    if phase == "report"
                    else {}
                ),
            )
        )

        def _fake_stream(*args, **kwargs):
            yield {
                "stage": "emotion",
                "data": {
                    "emotion_distribution": {"anger": 0.3, "fear": 0.2, "neutral": 0.5},
                    "stance_distribution": {"support": 0.2, "doubt": 0.6, "neutral": 0.2},
                    "emotion_drivers": ["情绪化词汇"],
                    "stance_drivers": ["证据不足"],
                },
            }
            yield {
                "stage": "narratives",
                "data": {
                    "narratives": [
                        {
                            "title": "质疑持续发酵",
                            "stance": "doubt",
                            "probability": 0.6,
                            "trigger_keywords": ["爆料", "转发"],
                            "sample_message": "这事不对劲，继续看后续",
                        }
                    ]
                },
            }
            yield {
                "stage": "flashpoints",
                "data": {
                    "flashpoints": ["KOL 二次扩散"],
                    "timeline": [{"hour": 3, "event": "传播提速", "expected_reach": "万级"}],
                },
            }
            yield {
                "stage": "suggestion",
                "data": {
                    "suggestion": {
                        "summary": "优先发布证据化澄清并持续监测",
                        "actions": [
                            {
                                "priority": "high",
                                "category": "official",
                                "action": "2小时内发布澄清",
                                "timeline": "2小时内",
                                "responsible": "公关部",
                            }
                        ],
                    }
                },
            }

        stack.enter_context(patch("app.api.routes_chat.simulate_opinion_stream", _fake_stream))

        raw_simulate = _stream_text(client, session_id, "/simulate")
        simulate_events = _parse_sse(raw_simulate)
        _assert_stage_order(simulate_events, "simulate")
        _assert_done_event(simulate_events)

    print("SSE acceptance checks passed for 4 paths.")


if __name__ == "__main__":
    main()
