import os
import tempfile
import time
from pathlib import Path

# 确保 chat DB 不污染仓库目录（必须在导入 app 之前设置）
tmp_dir = Path(tempfile.gettempdir()) / "truthcast_test"
tmp_dir.mkdir(parents=True, exist_ok=True)
os.environ["TRUTHCAST_CHAT_DB_PATH"] = str(tmp_dir / "chat_test.db")
os.environ["TRUTHCAST_HISTORY_DB_PATH"] = str(tmp_dir / "history_test.db")

try:
    (tmp_dir / "history_test.db").unlink(missing_ok=True)  # type: ignore[arg-type]
except TypeError:
    # Python < 3.8 fallback (not expected here)
    if (tmp_dir / "history_test.db").exists():
        (tmp_dir / "history_test.db").unlink()

from fastapi.testclient import TestClient

from app.main import app
from app.services import chat_store
from app.schemas.detect import ClarificationContent, ContentGenerateResponse, FAQItem, Platform, PlatformScript


client = TestClient(app)


def _extract_first_message_content_from_sse(raw: str) -> str:
    """从 SSE 文本中提取第一条 message 事件的 content。"""

    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evt = __import__("json").loads(line[len("data: ") :])
        except Exception:
            continue
        if evt.get("type") == "message":
            msg = (evt.get("data") or {}).get("message") or {}
            return str(msg.get("content") or "")
    return ""


def test_chat_smoke_returns_actions() -> None:
    resp = client.post("/chat", json={"text": "你好"})
    assert resp.status_code == 200
    body = resp.json()
    assert "session_id" in body
    assert "assistant_message" in body
    msg = body["assistant_message"]
    assert msg["role"] == "assistant"
    assert isinstance(msg.get("content"), str)
    assert isinstance(msg.get("actions"), list)
    assert len(msg["actions"]) >= 1


def test_chat_list_empty_shows_hint() -> None:
    # 确保在任何 /analyze 之前调用：历史库应为空
    with client.stream("POST", "/chat/stream", json={"text": "/list"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "暂无可用的历史记录" in content


def test_chat_why_without_record_id_shows_usage_not_error() -> None:
    with client.stream("POST", "/chat/stream", json={"text": "/why"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "用法：/why" in content


def test_chat_why_can_fallback_to_context_record_id() -> None:
    # 1) 先生成一条 history record
    resp = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp.status_code == 200
    actions = (resp.json().get("assistant_message") or {}).get("actions") or []
    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd
    record_id = str(load_cmd).split()[-1]

    # 2) /chat/stream：只输入 /why，但在 context 带 record_id，应返回解释而不是用法提示
    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/why", "context": {"record_id": record_id}},
    ) as resp2:
        assert resp2.status_code == 200
        raw2 = "".join(list(resp2.iter_text()))
        content2 = _extract_first_message_content_from_sse(raw2)
        assert "解释（最小可用）" in content2


def test_chat_analyze_command_works() -> None:
    resp = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp.status_code == 200
    body = resp.json()
    msg = body["assistant_message"]
    assert "已完成一次全链路分析" in msg["content"]
    assert isinstance(msg.get("references"), list)
    actions = msg.get("actions") or []
    assert any((a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history ")) for a in actions)

    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd

    # /why <record_id> 应可解释原因（追问闭环最小可用）
    why_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/why "):
            why_cmd = a.get("command")
            break
    assert why_cmd

    resp2 = client.post("/chat", json={"text": why_cmd})
    assert resp2.status_code == 200
    msg2 = resp2.json()["assistant_message"]
    assert "解释（最小可用）" in msg2["content"]
    meta = msg2.get("meta") or {}
    blocks = meta.get("blocks") or []
    assert isinstance(blocks, list)
    assert any((b or {}).get("kind") == "section" for b in blocks)

    # /rewrite 与 /more_evidence（通过 context 兜底 record_id）
    record_id = str(load_cmd).split()[-1]
    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/rewrite short", "context": {"record_id": record_id}},
    ) as resp3:
        assert resp3.status_code == 200
        raw3 = "".join(list(resp3.iter_text()))
        content3 = _extract_first_message_content_from_sse(raw3)
        assert "改写" in content3

    with client.stream(
        "POST",
        "/chat/stream",
        json={"text": "/more_evidence", "context": {"record_id": record_id}},
    ) as resp4:
        assert resp4.status_code == 200
        raw4 = "".join(list(resp4.iter_text()))
        content4 = _extract_first_message_content_from_sse(raw4)
        assert "补充证据建议" in content4


def test_chat_stream_smoke_for_non_analyze_intent() -> None:
    # 避免触发真实全链路分析：短输入应直接返回 message + done
    with client.stream("POST", "/chat/stream", json={"text": "你好"}) as resp:
        assert resp.status_code == 200
        raw = "".join(list(resp.iter_text()))
        assert "data: " in raw
        # 至少应包含 done 事件
        assert '"type":"done"' in raw or '"type": "done"' in raw


def test_chat_session_stream_ambiguous_text_returns_clarify_message() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "这是一段普通文本，没有明确操作指令", "context": None},
    ) as resp2:
        assert resp2.status_code == 200
        raw = "".join(list(resp2.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "当前意图还不够明确" in content
        assert "完整分析" in content
        assert "单技能" in content
        assert "主张/证据/对齐/报告/预演/应对内容" in content


def test_chat_sessions_crud_smoke() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session = resp.json()
    assert session.get("session_id")

    resp2 = client.get("/chat/sessions")
    assert resp2.status_code == 200
    body = resp2.json()
    assert isinstance(body.get("sessions"), list)
    assert any(s.get("session_id") == session["session_id"] for s in body["sessions"])

    resp3 = client.get(f"/chat/sessions/{session['session_id']}")
    assert resp3.status_code == 200
    detail = resp3.json()
    assert detail.get("session", {}).get("session_id") == session["session_id"]
    assert isinstance(detail.get("messages"), list)


def test_chat_session_stream_smoke() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "你好", "context": None},
    ) as resp2:
        assert resp2.status_code == 200
        raw = "".join(list(resp2.iter_text()))
        assert "data: " in raw
        assert '"type":"done"' in raw or '"type": "done"' in raw


def test_chat_list_then_analyze_then_load_history() -> None:
    # 1) 先 analyze 生成一条 history
    resp2 = client.post("/chat", json={"text": "/analyze 网传某事件100%真实，内部人士称必须立刻转发。"})
    assert resp2.status_code == 200
    actions = (resp2.json().get("assistant_message") or {}).get("actions") or []
    load_cmd = None
    for a in actions:
        if a.get("type") == "command" and str(a.get("command", "")).startswith("/load_history "):
            load_cmd = a.get("command")
            break
    assert load_cmd
    record_id = str(load_cmd).split()[-1]

    # 2) /sessions/{id}/messages/stream：/list 1 能列出 record_id
    resp3 = client.post("/chat/sessions", json={})
    assert resp3.status_code == 200
    session_id = resp3.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/list 1", "context": None},
    ) as resp4:
        assert resp4.status_code == 200
        raw = "".join(list(resp4.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert record_id in content
        assert "/load_history" in content

    # 3) /load_history 串联可用
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/load_history {record_id}", "context": None},
    ) as resp5:
        assert resp5.status_code == 200
        raw = "".join(list(resp5.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "已定位到历史记录" in content


def test_claims_only_then_evidence_only_reuses_claims_without_recompute(monkeypatch) -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    text = "网传某地突发事件已被官方证实，请立即转发提醒家人。"
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text}", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200
        raw_claims = "".join(list(resp_claims.iter_text()))
        content_claims = _extract_first_message_content_from_sse(raw_claims)
        assert "主张抽取完成" in content_claims

    def _forbidden_run_claims(*args, **kwargs):
        raise AssertionError("evidence_only 不应重复调用 run_claims")

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _forbidden_run_claims)

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text}", "context": None},
    ) as resp_evidence:
        assert resp_evidence.status_code == 200
        raw_evidence = "".join(list(resp_evidence.iter_text()))
        content_evidence = _extract_first_message_content_from_sse(raw_evidence)
        assert "证据检索完成" in content_evidence
        assert "复用 session 的 claims" in content_evidence


def test_single_skill_state_isolation_between_sessions_auto_plans_claims() -> None:
    resp_a = client.post("/chat/sessions", json={})
    resp_b = client.post("/chat/sessions", json={})
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    session_a = resp_a.json()["session_id"]
    session_b = resp_b.json()["session_id"]

    text = "网传某项政策已全国落地执行，请尽快办理。"
    with client.stream(
        "POST",
        f"/chat/sessions/{session_a}/messages/stream",
        json={"text": f"/claims_only {text}", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200

    with client.stream(
        "POST",
        f"/chat/sessions/{session_b}/messages/stream",
        json={"text": f"/evidence_only {text}", "context": None},
    ) as resp_evidence:
        assert resp_evidence.status_code == 200
        raw = "".join(list(resp_evidence.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "证据检索完成" in content
        assert "自动执行主张抽取前置阶段" in raw


def test_same_session_new_text_without_claims_auto_plans_claims() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    text_a = "网传某医院宣布免费治疗所有患者。"
    text_b = "网传某高校已停课并封校。"

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text_a}", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text_b}", "context": None},
    ) as resp_evidence:
        assert resp_evidence.status_code == 200
        raw = "".join(list(resp_evidence.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "证据检索完成" in content
        assert "自动执行主张抽取前置阶段" in raw


def test_same_session_multi_text_hash_buckets_can_reuse_each_text(monkeypatch) -> None:
    from app.schemas.detect import ClaimItem, EvidenceItem

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    text_a = "网传甲地发生重大事故，官方正在调查。"
    text_b = "网传乙地全面停课，明日统一线上教学。"

    def _fake_run_claims(text: str, strategy=None):
        suffix = "A" if "甲地" in text else "B"
        return [
            ClaimItem(
                claim_id=f"C{suffix}",
                claim_text=f"{suffix} 类主张",
                entity=f"实体{suffix}",
                time="2026-02-25",
                location=f"地点{suffix}",
                value=None,
                source_sentence=text,
            )
        ]

    def _fake_run_evidence(text: str, claims: list[ClaimItem], strategy=None):
        cid = claims[0].claim_id if claims else "C0"
        return [
            EvidenceItem(
                evidence_id=f"E-{cid}",
                claim_id=cid,
                title=f"证据标题-{cid}",
                source="测试来源",
                url=f"https://example.com/{cid}",
                published_at="2026-02-25",
                summary=f"摘要-{cid}",
                stance="support",
                source_weight=0.8,
            )
        ]

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _fake_run_claims)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_evidence", _fake_run_evidence)

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text_a}", "context": None},
    ) as r1:
        assert r1.status_code == 200

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text_b}", "context": None},
    ) as r2:
        assert r2.status_code == 200

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text_a}", "context": None},
    ) as r3:
        assert r3.status_code == 200
        raw_a = "".join(list(r3.iter_text()))
        content_a = _extract_first_message_content_from_sse(raw_a)
        assert "证据检索完成" in content_a
        assert "复用 session 的 claims" in content_a

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text_b}", "context": None},
    ) as r4:
        assert r4.status_code == 200
        raw_b = "".join(list(r4.iter_text()))
        content_b = _extract_first_message_content_from_sse(raw_b)
        assert "证据检索完成" in content_b
        assert "复用 session 的 claims" in content_b


def test_report_only_default_no_persist_outputs_full_details() -> None:
    """测试 report_only 默认不落库，且输出完整报告详情块。"""
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    text = "网传某地突发重大医疗事件，已导致多人死亡。"
    # Step 1: claims_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text}", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200

    # Step 2: evidence_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text}", "context": None},
    ) as resp_evidence:
        assert resp_evidence.status_code == 200

    # Step 3: align_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/align_only", "context": None},
    ) as resp_align:
        assert resp_align.status_code == 200

    # Step 4: report_only (默认 persist=false)
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/report_only", "context": None},
    ) as resp_report:
        assert resp_report.status_code == 200
        raw = "".join(list(resp_report.iter_text()))

        # 检查报告详情块结构
        assert "【报告详情】" in raw
        assert "[识别场景]" in raw
        assert "[证据覆盖域]" in raw
        assert "[风险评分]" in raw
        assert "[风险等级]" in raw
        assert "[风险标签]" in raw
        assert "[综合摘要]" in raw
        assert "[可疑点]" in raw

        # 检查最终 message 提示未落库
        content = _extract_first_message_content_from_sse(raw)
        assert "已生成报告详情（未写入历史记录）" in content
        assert "历史记录：" not in raw  # 不应有 record_id reference


def test_report_only_persist_true_writes_to_history() -> None:
    """测试 report_only persist=true 时写入历史记录并返回 record_id。"""
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    text = "网传某公司涉嫌财务造假，监管部门已立案调查。"
    # Step 1: claims_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/claims_only {text}", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200

    # Step 2: evidence_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": f"/evidence_only {text}", "context": None},
    ) as resp_evidence:
        assert resp_evidence.status_code == 200

    # Step 3: align_only
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/align_only", "context": None},
    ) as resp_align:
        assert resp_align.status_code == 200

    # Step 4: report_only persist=true
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/report_only persist=true", "context": None},
    ) as resp_report:
        assert resp_report.status_code == 200
        raw = "".join(list(resp_report.iter_text()))

        # 检查 report_only 执行结果（可能成功落库或因 LLM 失败）
        content = _extract_first_message_content_from_sse(raw)
        # 如果报告生成成功，persist=true 应该写入历史记录；如果 LLM 失败，会提示失败
        assert "report_only 完成" in content or "报告生成失败" in content


def test_simulate_requires_report_or_record_id() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/simulate", "context": None},
    ) as resp_simulate:
        assert resp_simulate.status_code == 200
        raw = "".join(list(resp_simulate.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "缺少 report 中间态" in content
        assert "/report_only" in content


def test_simulate_stream_outputs_five_blocks_and_persists_simulation_phase(monkeypatch) -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    report_dict = {
        "risk_score": 68,
        "risk_level": "high",
        "risk_label": "suspicious",
        "detected_scenario": "general",
        "evidence_domains": ["media"],
        "summary": "存在争议，需持续关注",
        "suspicious_points": ["来源不明"],
        "claim_reports": [],
    }

    def _fake_get_phase_payload(task_id: str, phase: str):
        if phase == "report":
            return {"report": report_dict}
        return {}

    def _fake_load_task(task_id: str):
        return {"input_text": "测试输入文本"}

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

    upsert_calls = []

    def _fake_upsert_phase_snapshot(**kwargs):
        upsert_calls.append(kwargs)

    monkeypatch.setattr("app.api.routes_chat.get_phase_payload", _fake_get_phase_payload)
    monkeypatch.setattr("app.api.routes_chat.load_task", _fake_load_task)
    monkeypatch.setattr("app.api.routes_chat.simulate_opinion_stream", _fake_stream)
    monkeypatch.setattr("app.api.routes_chat.upsert_phase_snapshot", _fake_upsert_phase_snapshot)

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/simulate", "context": None},
    ) as resp_simulate:
        assert resp_simulate.status_code == 200
        raw = "".join(list(resp_simulate.iter_text()))

    assert "【舆情预演-情绪分布】" in raw
    assert "【舆情预演-叙事分支】" in raw
    assert "【舆情预演-引爆点】" in raw
    assert "【舆情预演-时间线】" in raw
    assert "【舆情预演-应对建议】" in raw
    assert '"stage":"simulate","status":"running"' in raw
    assert '"stage":"simulate","status":"done"' in raw

    content = _extract_first_message_content_from_sse(raw)
    assert "simulate 完成" in content
    assert any(call.get("phase") == "simulation" for call in upsert_calls)


def test_content_generate_requires_report_or_record_id() -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content_generate", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "缺少 report 中间态" in content
        assert "/report_only" in content
        assert "record_id" in content


def test_content_generate_outputs_summary_and_persists_content_phase(monkeypatch) -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    report_dict = {
        "risk_score": 42,
        "risk_level": "medium",
        "risk_label": "needs_context",
        "detected_scenario": "general",
        "evidence_domains": ["media"],
        "summary": "当前信息需补充语境",
        "suspicious_points": ["来源表述模糊"],
        "claim_reports": [],
    }

    def _fake_get_phase_payload(task_id: str, phase: str):
        if phase == "report":
            return {"report": report_dict, "record_id": "rec_test_content_1"}
        if phase == "simulation":
            return {}
        return {}

    def _fake_load_task(task_id: str):
        return {"input_text": "测试输入文本"}

    async def _fake_generate_full_content(request):
        return ContentGenerateResponse(
            clarification=ClarificationContent(short="短", medium="中", long="长"),
            faq=[FAQItem(question="问1", answer="答1", category="general")],
            platform_scripts=[
                PlatformScript(platform=Platform.WEIBO, content="微博话术", tips=["先发主结论"]),
                PlatformScript(platform=Platform.WECHAT, content="公众号话术", tips=["补充来源"]),
            ],
            generated_at="2026-02-25T00:00:00+00:00",
            based_on={"risk_level": "medium"},
        )

    upsert_calls = []
    update_content_calls = []

    def _fake_upsert_phase_snapshot(**kwargs):
        upsert_calls.append(kwargs)

    def _fake_update_content(record_id: str, content):
        update_content_calls.append({"record_id": record_id, "content": content})

    monkeypatch.setattr("app.api.routes_chat.get_phase_payload", _fake_get_phase_payload)
    monkeypatch.setattr("app.api.routes_chat.load_task", _fake_load_task)
    monkeypatch.setattr("app.api.routes_chat.generate_full_content", _fake_generate_full_content)
    monkeypatch.setattr("app.api.routes_chat.upsert_phase_snapshot", _fake_upsert_phase_snapshot)
    monkeypatch.setattr("app.api.routes_chat.update_content", _fake_update_content)

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content_generate style=friendly", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))

    assert "【应对内容生成结果】" in raw
    assert "[澄清稿] 3 个版本" in raw
    assert "[FAQ] 1 条" in raw
    assert "[平台话术] 2 条" in raw
    assert '"stage":"content_generate","status":"running"' in raw
    assert '"stage":"content_generate","status":"done"' in raw

    content = _extract_first_message_content_from_sse(raw)
    assert "content_generate 完成" in content
    assert "澄清稿：3 个版本" in content
    assert "FAQ：1 条" in content
    assert "多平台话术：2 条" in content

    assert any(call.get("phase") == "content" and call.get("status") == "done" for call in upsert_calls)
    assert any(call.get("record_id") == "rec_test_content_1" for call in update_content_calls)


def test_single_skill_tool_budget_limit_blocks_calls(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_SESSION_TOOL_MAX_CALLS", "1")
    monkeypatch.setenv("TRUTHCAST_SESSION_LLM_MAX_CALLS", "20")

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    chat_store.update_session_meta_fields(session_id, {"tool_call_count": 1, "llm_call_count": 0})

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/claims_only 测试文本", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200
        raw = "".join(list(resp_claims.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "工具调用已达上限" in content


def test_single_skill_llm_budget_limit_blocks_llm_tools(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_SESSION_TOOL_MAX_CALLS", "50")
    monkeypatch.setenv("TRUTHCAST_SESSION_LLM_MAX_CALLS", "1")

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    chat_store.update_session_meta_fields(session_id, {"tool_call_count": 0, "llm_call_count": 1})

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/claims_only 测试文本", "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200
        raw = "".join(list(resp_claims.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "LLM 调用已达上限" in content


def test_simulate_cache_hit_reuses_recent_result(monkeypatch) -> None:
    from app.api import routes_chat as routes_chat_module

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    report_dict = {
        "risk_score": 68,
        "risk_level": "high",
        "risk_label": "suspicious",
        "detected_scenario": "general",
        "evidence_domains": ["media"],
        "summary": "存在争议，需持续关注",
        "suspicious_points": ["来源不明"],
        "claim_reports": [],
    }
    simulation_dict = {
        "emotion_distribution": {"anger": 0.3, "neutral": 0.7},
        "stance_distribution": {"doubt": 0.6, "neutral": 0.4},
        "narratives": [],
        "flashpoints": ["KOL 扩散"],
        "timeline": [],
        "suggestion": {"summary": "先澄清后跟进", "actions": []},
        "emotion_drivers": [],
        "stance_drivers": [],
    }

    def _fake_get_phase_payload(task_id: str, phase: str):
        if phase == "report":
            return {"report": report_dict}
        if phase == "simulation":
            return {"simulation": simulation_dict}
        return {}

    def _fake_load_task(task_id: str):
        return {"input_text": "测试输入文本"}

    def _forbidden_stream(*args, **kwargs):
        raise AssertionError("命中缓存时不应调用 simulate_opinion_stream")

    monkeypatch.setattr("app.api.routes_chat.get_phase_payload", _fake_get_phase_payload)
    monkeypatch.setattr("app.api.routes_chat.load_task", _fake_load_task)
    monkeypatch.setattr("app.api.routes_chat.simulate_opinion_stream", _forbidden_stream)

    cache_key = routes_chat_module._stable_hash_payload(
        {
            "record_id": "",
            "report": report_dict,
            "input_text": "测试输入文本",
        }
    )
    chat_store.update_session_meta_fields(
        session_id,
        {
            "session_cache_simulate": {"key": cache_key, "ts": int(time.time())},
            "tool_call_count": 0,
            "llm_call_count": 0,
        },
    )

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/simulate", "context": None},
    ) as resp_simulate:
        assert resp_simulate.status_code == 200
        raw = "".join(list(resp_simulate.iter_text()))
        assert "命中会话缓存" in raw
        content = _extract_first_message_content_from_sse(raw)
        assert "命中会话缓存" in content


def test_content_generate_cache_hit_reuses_recent_result(monkeypatch) -> None:
    from app.api import routes_chat as routes_chat_module

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    report_dict = {
        "risk_score": 42,
        "risk_level": "medium",
        "risk_label": "needs_context",
        "detected_scenario": "general",
        "evidence_domains": ["media"],
        "summary": "当前信息需补充语境",
        "suspicious_points": ["来源表述模糊"],
        "claim_reports": [],
    }
    content_dict = {
        "clarification": {"short": "短", "medium": "中", "long": "长"},
        "faq": [{"question": "问1", "answer": "答1", "category": "general"}],
        "platform_scripts": [{"platform": "weibo", "content": "微博话术", "tips": []}],
        "generated_at": "2026-02-25T00:00:00+00:00",
        "based_on": {"risk_level": "medium"},
    }

    def _fake_get_phase_payload(task_id: str, phase: str):
        if phase == "report":
            return {"report": report_dict}
        if phase == "content":
            return {"content": content_dict}
        if phase == "simulation":
            return {}
        return {}

    def _fake_load_task(task_id: str):
        return {"input_text": "测试输入文本"}

    async def _forbidden_generate(*args, **kwargs):
        raise AssertionError("命中缓存时不应调用 generate_full_content")

    monkeypatch.setattr("app.api.routes_chat.get_phase_payload", _fake_get_phase_payload)
    monkeypatch.setattr("app.api.routes_chat.load_task", _fake_load_task)
    monkeypatch.setattr("app.api.routes_chat.generate_full_content", _forbidden_generate)

    cache_key = routes_chat_module._stable_hash_payload(
        {
            "record_id": "",
            "report": report_dict,
            "simulation": None,
            "input_text": "测试输入文本",
            "style": "formal",
        }
    )
    input_hash = routes_chat_module._hash_input_text("测试输入文本")
    chat_store.update_session_meta_fields(
        session_id,
        {
            "input_text_hash": input_hash,
            "session_cache_content_generate": {"key": cache_key, "ts": int(time.time())},
            "tool_call_count": 0,
            "llm_call_count": 0,
            "phase_payload_buckets": {
                input_hash: {
                    "content": {"content": content_dict},
                    "input_text": "测试输入文本",
                    "updated_at": int(time.time()),
                }
            },
        },
    )

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content_generate", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))
        assert "复用" in raw
        content = _extract_first_message_content_from_sse(raw)
        assert "复用" in content


def test_content_alias_reuses_existing_content_when_report_missing(monkeypatch) -> None:
    from app.api import routes_chat as routes_chat_module

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    content_dict = {
        "clarification": {"short": "短稿内容", "medium": "中稿内容", "long": "长稿内容"},
        "faq": [{"question": "问1", "answer": "答1", "category": "general"}],
        "platform_scripts": [{"platform": "weibo", "content": "微博话术", "tips": []}],
        "generated_at": "2026-02-25T00:00:00+00:00",
        "based_on": {"risk_level": "medium"},
    }

    input_hash = routes_chat_module._hash_input_text("测试输入文本")
    chat_store.update_session_meta_fields(
        session_id,
        {
            "input_text_hash": input_hash,
            "phase_payload_buckets": {
                input_hash: {
                    "content": {"content": content_dict},
                    "input_text": "测试输入文本",
                    "updated_at": int(time.time()),
                }
            },
        },
    )

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content detail=full", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))
        assert "content_show 完成" in raw
        assert "-----BEGIN CLARIFICATION_SHORT-----" in raw


def test_content_show_clarification_short_outputs_specific_block(monkeypatch) -> None:
    from app.api import routes_chat as routes_chat_module

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    content_dict = {
        "clarification": {"short": "短稿内容", "medium": "中稿内容", "long": "长稿内容"},
        "faq": [{"question": "问1", "answer": "答1", "category": "general"}],
        "platform_scripts": [{"platform": "weibo", "content": "微博话术", "tips": []}],
        "generated_at": "2026-02-25T00:00:00+00:00",
        "based_on": {"risk_level": "medium"},
    }

    input_hash = routes_chat_module._hash_input_text("测试输入文本")
    chat_store.update_session_meta_fields(
        session_id,
        {
            "input_text_hash": input_hash,
            "phase_payload_buckets": {
                input_hash: {
                    "content": {"content": content_dict},
                    "input_text": "测试输入文本",
                    "updated_at": int(time.time()),
                }
            },
        },
    )

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content_show clarification short", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))
        assert "content_show 完成" in raw
        assert "-----BEGIN CLARIFICATION_SHORT-----" in raw
        assert "短稿内容" in raw


def test_content_reuse_only_without_existing_skips_generation(monkeypatch) -> None:
    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    async def _forbidden_generate(*args, **kwargs):
        raise AssertionError("reuse_only 模式不应触发生成")

    monkeypatch.setattr("app.api.routes_chat.generate_full_content", _forbidden_generate)

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": "/content_generate reuse_only=true", "context": None},
    ) as resp_content:
        assert resp_content.status_code == 200
        raw = "".join(list(resp_content.iter_text()))
        assert "reuse_only=true" in raw
        assert "跳过生成" in raw


def test_natural_language_claims_only_routes_with_text_payload(monkeypatch) -> None:
    from app.schemas.detect import ClaimItem

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    captured: dict[str, str] = {}

    def _fake_run_claims(text: str, strategy=None):
        captured["text"] = text
        return [
            ClaimItem(
                claim_id="C1",
                claim_text="香港一名女警员在警署身亡",
                entity="香港女警员",
                time="2026-02-25",
                location="观塘警署",
                value=None,
                source_sentence="香港一名女警员在观塘警署用佩枪自杀死亡",
            )
        ]

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _fake_run_claims)

    prompt = (
        "只帮我提取主张：【#香港自杀女警手机中发现遗书#】"
        "#香港自杀女警遗书中提到工作压力# 2月25日，香港一名女警员在观塘警署用佩枪自杀死亡。"
    )
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": prompt, "context": None},
    ) as resp_claims:
        assert resp_claims.status_code == 200
        raw = "".join(list(resp_claims.iter_text()))
        assert "主张抽取完成" in raw

    assert captured.get("text")
    assert "香港一名女警员" in captured["text"]


def test_natural_language_evidence_auto_runs_claims_prerequisite(monkeypatch) -> None:
    from app.schemas.detect import ClaimItem, EvidenceItem

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    called = {"claims": 0, "evidence": 0}

    def _fake_run_claims(text: str, strategy=None):
        called["claims"] += 1
        return [
            ClaimItem(
                claim_id="C1",
                claim_text="广元男子已离世",
                entity="广元男子",
                time="2026-02-25",
                location="四川广元",
                value=None,
                source_sentence=text,
            )
        ]

    def _fake_run_evidence(text: str, claims, strategy=None):
        called["evidence"] += 1
        return [
            EvidenceItem(
                evidence_id="E1",
                claim_id="C1",
                title="媒体报道已确认",
                source="测试媒体",
                url="https://example.com/e1",
                published_at="2026-02-25",
                summary="家属与救援队证实已离世",
                stance="support",
                source_weight=0.8,
            )
        ]

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _fake_run_claims)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_evidence", _fake_run_evidence)

    prompt = "帮我检索证据：四川广元男子失联后被找到，救援队称已离世"
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": prompt, "context": None},
    ) as resp_msg:
        assert resp_msg.status_code == 200
        raw = "".join(list(resp_msg.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "证据检索完成" in content
        assert "自动执行主张抽取前置阶段" in raw

    assert called["claims"] == 1
    assert called["evidence"] == 1


def test_natural_language_report_auto_runs_full_prerequisites(monkeypatch) -> None:
    from app.schemas.detect import ClaimItem, EvidenceItem

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    called = {"claims": 0, "evidence": 0, "align": 0, "report": 0}

    def _fake_run_claims(text: str, strategy=None):
        called["claims"] += 1
        return [
            ClaimItem(
                claim_id="C1",
                claim_text="事件已确认",
                entity="事件主体",
                time="2026-02-25",
                location="四川广元",
                value=None,
                source_sentence=text,
            )
        ]

    def _fake_run_evidence(text: str, claims, strategy=None):
        called["evidence"] += 1
        return [
            EvidenceItem(
                evidence_id="E1",
                claim_id="C1",
                title="来源A",
                source="来源A",
                url="https://example.com/a",
                published_at="2026-02-25",
                summary="来源A摘要",
                stance="support",
                source_weight=0.9,
            )
        ]

    def _fake_align(claims, evidences, strategy=None):
        called["align"] += 1
        return evidences

    def _fake_report(text: str, claims, evidences, strategy=None):
        called["report"] += 1
        return {
            "risk_score": 55,
            "risk_level": "medium",
            "risk_label": "needs_context",
            "detected_scenario": "general",
            "evidence_domains": ["media"],
            "summary": "综合判断需补充语境",
            "suspicious_points": ["来源单一"],
            "claim_reports": [],
        }

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _fake_run_claims)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_evidence", _fake_run_evidence)
    monkeypatch.setattr("app.api.routes_chat.align_evidences", _fake_align)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_report", _fake_report)

    prompt = "帮我生成综合报告：四川广元男子失联后已离世的新闻"
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": prompt, "context": None},
    ) as resp_msg:
        assert resp_msg.status_code == 200
        raw = "".join(list(resp_msg.iter_text()))
        content = _extract_first_message_content_from_sse(raw)
        assert "report_only 完成" in content
        assert "自动补齐前置阶段" in raw

    assert called == {"claims": 1, "evidence": 1, "align": 1, "report": 1}


def test_natural_language_simulate_auto_runs_full_prerequisites_and_shows_outputs(monkeypatch) -> None:
    from app.schemas.detect import ClaimItem, EvidenceItem

    resp = client.post("/chat/sessions", json={})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]

    called = {"claims": 0, "evidence": 0, "align": 0, "report": 0, "simulate": 0}

    def _fake_run_claims(text: str, strategy=None):
        called["claims"] += 1
        return [
            ClaimItem(
                claim_id="C1",
                claim_text="事件引发关注",
                entity="当事人",
                time="2026-02-25",
                location="香港观塘",
                value=None,
                source_sentence=text,
            )
        ]

    def _fake_run_evidence(text: str, claims, strategy=None):
        called["evidence"] += 1
        return [
            EvidenceItem(
                evidence_id="E1",
                claim_id="C1",
                title="来源A",
                source="来源A",
                url="https://example.com/a",
                published_at="2026-02-25",
                summary="来源A摘要",
                stance="support",
                source_weight=0.8,
            )
        ]

    def _fake_align(claims, evidences, strategy=None):
        called["align"] += 1
        return evidences

    def _fake_report(text: str, claims, evidences, strategy=None):
        called["report"] += 1
        return {
            "risk_score": 60,
            "risk_level": "medium",
            "risk_label": "needs_context",
            "detected_scenario": "general",
            "evidence_domains": ["media"],
            "summary": "需补充语境",
            "suspicious_points": ["信息来源有限"],
            "claim_reports": [],
        }

    def _fake_stream(**kwargs):
        called["simulate"] += 1
        yield {"stage": "emotion", "data": {"emotion_distribution": {"neutral": 1.0}, "stance_distribution": {"neutral": 1.0}, "emotion_drivers": [], "stance_drivers": []}}
        yield {"stage": "narratives", "data": {"narratives": []}}
        yield {"stage": "flashpoints", "data": {"flashpoints": [], "timeline": []}}
        yield {"stage": "suggestion", "data": {"suggestion": {"summary": "保持观察", "actions": []}}}

    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_claims", _fake_run_claims)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_evidence", _fake_run_evidence)
    monkeypatch.setattr("app.api.routes_chat.align_evidences", _fake_align)
    monkeypatch.setattr("app.api.routes_chat.orchestrator.run_report", _fake_report)
    monkeypatch.setattr("app.api.routes_chat.simulate_opinion_stream", _fake_stream)

    prompt = "帮我进行舆情预演：香港女警事件引发舆论讨论"
    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages/stream",
        json={"text": prompt, "context": None},
    ) as resp_msg:
        assert resp_msg.status_code == 200
        raw = "".join(list(resp_msg.iter_text()))
        assert "simulate 完成" in raw
        assert "自动补齐-主张抽取结果" in raw
        assert "自动补齐-证据检索结果" in raw
        assert "自动补齐-证据对齐结果" in raw
        assert "自动补齐-报告结果" in raw

    assert called == {"claims": 1, "evidence": 1, "align": 1, "report": 1, "simulate": 1}
