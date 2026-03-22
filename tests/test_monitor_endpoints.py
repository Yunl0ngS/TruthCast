import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def test_monitor_alert_engine_uses_configured_cooldown(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_ALERT_COOLDOWN_MINUTES", "45")

    from app.api import routes_monitor

    assert routes_monitor._alert_cooldown_minutes() == 45


@pytest.mark.anyio
async def test_monitor_subscription_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_MONITOR_DEFAULT_USER_ID", "demo-user")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_response = await client.post(
            "/monitor/subscriptions",
            json={
                "name": "疫苗谣言监测",
                "type": "keyword",
                "keywords": ["疫苗", "副作用"],
                "platforms": ["weibo", "douyin"],
                "exclude_keywords": ["辟谣"],
                "trigger_mode": "threshold",
                "risk_threshold": 75,
                "notify_channels": ["webhook"],
                "notify_config": {"webhook": {"url": "https://example.com/hook"}},
            },
        )
        assert create_response.status_code == 200
        created = create_response.json()
        assert created["name"] == "疫苗谣言监测"
        assert created["platforms"] == ["weibo", "douyin"]

        list_response = await client.get("/monitor/subscriptions")
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == created["id"]

        detail_response = await client.get(f"/monitor/subscriptions/{created['id']}")
        assert detail_response.status_code == 200
        assert detail_response.json()["risk_threshold"] == 75

        update_response = await client.patch(
            f"/monitor/subscriptions/{created['id']}",
            json={"is_active": False, "risk_threshold": 82},
        )
        assert update_response.status_code == 200
        assert update_response.json()["is_active"] is False
        assert update_response.json()["risk_threshold"] == 82

        delete_response = await client.delete(f"/monitor/subscriptions/{created['id']}")
        assert delete_response.status_code == 200
        assert delete_response.json() == {"status": "ok"}

        missing_response = await client.get(f"/monitor/subscriptions/{created['id']}")
        assert missing_response.status_code == 404


@pytest.mark.anyio
async def test_monitor_scan_and_hot_items_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.api import routes_monitor
    from app.schemas.monitor import HotItem, TrendDirection

    async def _fake_fetch_all():
        return {
            "weibo": [
                HotItem(
                    id="weibo_hot_1",
                    platform="weibo",
                    title="某地突发事件登上热搜",
                    url="https://example.com/hot/1",
                    hot_value=120,
                    last_hot_value=0,
                    rank=1,
                    trend=TrendDirection.NEW,
                )
            ]
        }

    monkeypatch.setattr(routes_monitor.hot_items_service, "fetch_all", _fake_fetch_all)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        scan_response = await client.post("/monitor/scan", json={})
        assert scan_response.status_code == 200
        assert scan_response.json()["scanned_platforms"] == ["weibo"]
        assert scan_response.json()["saved_count"] == 1

        list_response = await client.get("/monitor/hot-items")
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == "weibo_hot_1"
        assert items[0]["platform"] == "weibo"


@pytest.mark.anyio
async def test_monitor_scan_endpoint_respects_auto_analyze_flag(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    import app.main as main_module

    captured = {}

    class _FakeScheduler:
        async def trigger_manual_scan(self, platforms=None, auto_analyze=True):
            captured["platforms"] = platforms
            captured["auto_analyze"] = auto_analyze
            return {
                "scanned_platforms": platforms or ["thepaper"],
                "saved_count": 2,
                "total_fetched": 2,
                "window_id": "window_2026032116",
                "auto_analyze": auto_analyze,
                "analysis_scheduled": auto_analyze,
            }

    monkeypatch.setattr(main_module, "monitor_scheduler", _FakeScheduler())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/monitor/scan",
            json={"platforms": ["thepaper"], "auto_analyze": False},
        )

    assert response.status_code == 200
    assert captured == {
        "platforms": ["thepaper"],
        "auto_analyze": False,
    }
    assert response.json()["analysis_scheduled"] is False
    assert response.json()["window_id"] == "window_2026032116"


@pytest.mark.anyio
async def test_monitor_scan_endpoint_uses_manual_scan_auto_analyze_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_MONITOR_MANUAL_SCAN_AUTO_ANALYZE", "true")

    import app.main as main_module

    captured = {}

    class _FakeScheduler:
        async def trigger_manual_scan(self, platforms=None, auto_analyze=True):
            captured["platforms"] = platforms
            captured["auto_analyze"] = auto_analyze
            return {
                "scanned_platforms": ["zaobao"],
                "saved_count": 1,
                "total_fetched": 1,
                "window_id": "window_2026032116",
                "auto_analyze": auto_analyze,
                "analysis_scheduled": auto_analyze,
            }

    monkeypatch.setattr(main_module, "monitor_scheduler", _FakeScheduler())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/monitor/scan", json={})

    assert response.status_code == 200
    assert captured["platforms"] is None
    assert captured["auto_analyze"] is True
    assert response.json()["analysis_scheduled"] is True


@pytest.mark.anyio
async def test_monitor_scan_triggers_alert_checks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_MONITOR_MANUAL_SCAN_AUTO_ANALYZE", "true")

    from app.api import routes_monitor
    from app.schemas.monitor import HotItem, TrendDirection

    async def _fake_fetch_all():
        return {
            "weibo": [
                HotItem(
                    id="weibo_hot_alert_scan",
                    platform="weibo",
                    title="扫描链路触发预警",
                    url="https://example.com/hot/scan-alert",
                    hot_value=150,
                    last_hot_value=0,
                    rank=3,
                    trend=TrendDirection.NEW,
                )
            ]
        }

    captured = {}

    async def _fake_check_and_alert(items, platform):
        captured["platform"] = platform
        captured["item_ids"] = [item.id for item in items]
        return []

    monkeypatch.setattr(routes_monitor.hot_items_service, "fetch_all", _fake_fetch_all)
    monkeypatch.setattr(routes_monitor.alert_engine, "check_and_alert", _fake_check_and_alert)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/monitor/scan", json={"auto_analyze": True})
        assert response.status_code == 200

    assert captured == {
        "platform": "weibo",
        "item_ids": ["weibo_hot_alert_scan"],
    }


@pytest.mark.anyio
async def test_monitor_alert_endpoints(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_MONITOR_DEFAULT_USER_ID", "demo-user")

    from app.api import routes_monitor
    from app.schemas.monitor import (
        HotItem,
        NotifyChannel,
        SubscriptionCreate,
        SubscriptionType,
        TriggerMode,
        TrendDirection,
    )
    from app.services.monitor.alert_engine import AlertEngine
    from app.services.monitor.hot_items import HotItemsService
    from app.services.monitor.notifier import NotifierService
    from app.services.monitor.subscription import SubscriptionService
    from app.services.text_complexity import ScoreResult

    class _FakeNotifier(NotifierService):
        async def send(self, alert, subscriptions):
            return [{"channel": "webhook", "success": True, "message": "ok"}]

    async def _fake_risk(_text: str) -> ScoreResult:
        return ScoreResult(
            label="high_risk",
            score=91,
            confidence=0.95,
            reasons=["高风险"],
            strategy=None,
        )

    routes_monitor.alert_engine = AlertEngine(
        subscription_service=SubscriptionService(),
        hot_items_service=HotItemsService(),
        notifier=_FakeNotifier(),
        risk_evaluator=_fake_risk,
        cooldown_minutes=30,
    )

    await routes_monitor.subscription_service.create(
        SubscriptionCreate(
            name="突发事件订阅",
            type=SubscriptionType.KEYWORD,
            keywords=["突发事件"],
            platforms=["weibo"],
            trigger_mode=TriggerMode.HIT,
            notify_channels=[NotifyChannel.WEBHOOK],
            notify_config={"webhook": {"url": "https://example.com/hook"}},
        ),
        user_id="demo-user",
    )
    hot_item = HotItem(
        id="weibo_hot_2",
        platform="weibo",
        title="某地突发事件持续发酵",
        url="https://example.com/hot/2",
        hot_value=260,
        rank=2,
        trend=TrendDirection.NEW,
    )
    await routes_monitor.hot_items_service.save([hot_item])
    created_alerts = await routes_monitor.alert_engine.check_and_alert([hot_item], "weibo")
    assert len(created_alerts) == 1
    alert_id = created_alerts[0].id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        list_response = await client.get("/monitor/alerts")
        assert list_response.status_code == 200
        items = list_response.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == alert_id

        ack_response = await client.post(f"/monitor/alerts/{alert_id}/ack")
        assert ack_response.status_code == 200
        assert ack_response.json()["status"] == "ok"

        detail_response = await client.get(f"/monitor/alerts/{alert_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["status"] == "acknowledged"

        assess_response = await client.post("/monitor/hot-items/weibo_hot_2/assess")
        assert assess_response.status_code == 200
        assert assess_response.json()["risk_score"] == 91
        assert assess_response.json()["risk_level"] == "high_risk"


@pytest.mark.anyio
async def test_monitor_status_endpoint_reports_scheduler_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    import app.main as main_module

    class _FakeScheduler:
        is_running = True

        def get_runtime_status(self):
            return {
                "running": True,
                "adaptive_mode": True,
                "manual_scan_auto_analyze_default": True,
                "enabled_platforms": [
                    {"key": "thepaper", "display_name": "澎湃新闻"},
                    {"key": "zaobao", "display_name": "联合早报"},
                ],
                "default_interval_minutes": 10,
                "effective_interval_minutes": 5,
                "platform_intervals": {"weibo": 5},
                "last_scan_at": "2026-03-20T08:00:00+00:00",
                "last_scan_summary": {"weibo": {"fetched": 3, "alert_candidates": 1}},
                "failure_count": 2,
                "platform_failures": {"weibo": 1, "zhihu": 1},
                "last_error": {
                    "platform": "zhihu",
                    "message": "service unavailable",
                    "at": "2026-03-20T08:05:00+00:00",
                },
                "last_scan_duration_ms": 842,
                "platform_durations_ms": {"weibo": 320, "zhihu": 180},
            }

    monkeypatch.setattr(main_module, "monitor_scheduler", _FakeScheduler())

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/monitor/status")
        assert response.status_code == 200
        body = response.json()
        assert body["running"] is True
        assert body["platform_intervals"]["weibo"] == 5
        assert body["manual_scan_auto_analyze_default"] is True
        assert body["enabled_platforms"][0]["key"] == "thepaper"
        assert body["last_scan_summary"]["weibo"]["alert_candidates"] == 1
        assert body["failure_count"] == 2
        assert body["last_error"]["platform"] == "zhihu"
        assert body["last_scan_duration_ms"] == 842
        assert body["platform_durations_ms"]["weibo"] == 320


@pytest.mark.anyio
async def test_monitor_analysis_result_endpoints_and_manual_content_generation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    monkeypatch.setenv("TRUTHCAST_HISTORY_DB_PATH", str(tmp_path / "history.db"))

    from app.schemas.monitor import AnalysisStage, MonitorAnalysisResult
    from app.services.history_store import get_history, save_report
    from app.services.monitor.store import save_monitor_analysis_result
    from app.api import routes_monitor

    history_record_id = save_report(
        input_text="新闻正文内容",
        report={
            "risk_score": 72,
            "risk_level": "critical",
            "risk_label": "likely_misinformation",
            "detected_scenario": "general",
            "evidence_domains": ["general"],
            "summary": "报告摘要",
            "suspicious_points": ["疑点"],
            "claim_reports": [],
        },
        detect_data={"label": "suspicious", "confidence": 0.8, "score": 65, "reasons": ["疑点"]},
        simulation={
            "emotion_distribution": {"anger": 0.6, "neutral": 0.4},
            "stance_distribution": {"questioning": 0.7, "neutral": 0.3},
            "narratives": [],
            "flashpoints": ["扩散加速"],
            "suggestion": {"summary": "建议回应", "actions": []},
        },
    )

    saved = save_monitor_analysis_result(
        MonitorAnalysisResult(
            id="analysis_ready",
            hot_item_id="hot_ready",
            platform="thepaper",
            source_url="https://example.com/news/ready",
            crawl_status="done",
            crawl_title="已完成预演的新闻",
            crawl_content="新闻正文内容",
            crawl_publish_date="2026-03-20",
            risk_snapshot_score=65,
            risk_snapshot_label="suspicious",
            current_stage=AnalysisStage.SIMULATION,
            report_score=72,
            report_level="critical",
            history_record_id=history_record_id,
            simulation_status="done",
            content_generation_status="idle",
            report_data={
                "risk_score": 72,
                "risk_level": "critical",
                "risk_label": "likely_misinformation",
                "detected_scenario": "general",
                "evidence_domains": ["general"],
                "summary": "报告摘要",
                "suspicious_points": ["疑点"],
                "claim_reports": [],
            },
            simulation_data={
                "emotion_distribution": {"anger": 0.6, "neutral": 0.4},
                "stance_distribution": {"questioning": 0.7, "neutral": 0.3},
                "narratives": [],
                "flashpoints": ["扩散加速"],
                "suggestion": {"summary": "建议回应", "actions": []},
            },
        )
    )

    async def _fake_generate_content(request):
        return {
            "clarification": {"short": "短版", "medium": "中版", "long": "长版"},
            "faq": [],
            "platform_scripts": [],
            "generated_at": "2026-03-20T10:00:00+00:00",
            "based_on": {"platform": "thepaper"},
        }

    monkeypatch.setattr(routes_monitor, "generate_full_content", _fake_generate_content)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        list_response = await client.get("/monitor/analysis-results")
        assert list_response.status_code == 200
        assert list_response.json()["items"][0]["id"] == saved.id

        detail_response = await client.get(f"/monitor/analysis-results/{saved.id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["report_score"] == 72

        content_response = await client.post(f"/monitor/analysis-results/{saved.id}/generate-content")
        assert content_response.status_code == 200
        assert content_response.json()["status"] == "ok"
        assert content_response.json()["result_id"] == saved.id

    history = get_history(history_record_id)
    assert history is not None
    assert history["content"]["clarification"]["short"] == "短版"


@pytest.mark.anyio
async def test_monitor_window_endpoints_return_latest_and_history(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from datetime import datetime, timezone

    from app.schemas.monitor import (
        AnalysisStage,
        MonitorAnalysisResult,
        MonitorScanTriggerType,
        MonitorScanWindow,
        MonitorScanWindowStatus,
        MonitorWindowItem,
    )
    from app.services.monitor.store import (
        create_monitor_scan_window,
        save_monitor_analysis_result,
        save_monitor_window_item,
    )

    analysis = save_monitor_analysis_result(
        MonitorAnalysisResult(
            id="analysis_latest",
            hot_item_id="hot_latest",
            platform="thepaper",
            source_url="https://example.com/latest",
            dedupe_key="thepaper::latest::https://example.com/latest",
            crawl_status="done",
            current_stage=AnalysisStage.REPORT,
            risk_snapshot_score=58,
            risk_snapshot_label="suspicious",
            risk_snapshot_reasons=["最新窗口风险"],
            report_score=71,
            report_level="critical",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    latest_window = create_monitor_scan_window(
        MonitorScanWindow(
            id="window_latest",
            window_start=datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 3, 21, 17, 0, tzinfo=timezone.utc),
            trigger_type=MonitorScanTriggerType.SCHEDULED,
            status=MonitorScanWindowStatus.COMPLETED,
            platforms=["thepaper"],
            fetched_count=3,
            deduplicated_count=2,
            analyzed_count=1,
            duplicate_count=1,
        )
    )
    history_window = create_monitor_scan_window(
        MonitorScanWindow(
            id="window_history",
            window_start=datetime(2026, 3, 21, 15, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc),
            trigger_type=MonitorScanTriggerType.SCHEDULED,
            status=MonitorScanWindowStatus.COMPLETED,
            platforms=["thepaper"],
            fetched_count=2,
            deduplicated_count=2,
            analyzed_count=1,
            duplicate_count=0,
        )
    )

    save_monitor_window_item(
        MonitorWindowItem(
            id="latest_item",
            window_id=latest_window.id,
            platform="thepaper",
            hot_item_id="hot_latest",
            analysis_result_id=analysis.id,
            dedupe_key="thepaper::latest::https://example.com/latest",
            title="最新窗口新闻",
            url="https://example.com/latest",
            hot_value=101,
            rank=1,
            trend="new",
        )
    )
    save_monitor_window_item(
        MonitorWindowItem(
            id="history_item",
            window_id=history_window.id,
            platform="thepaper",
            hot_item_id="hot_history",
            analysis_result_id=None,
            dedupe_key="thepaper::history::https://example.com/history",
            title="历史窗口新闻",
            url="https://example.com/history",
            hot_value=66,
            rank=2,
            trend="stable",
        )
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        latest_response = await client.get("/monitor/windows/latest")
        assert latest_response.status_code == 200
        assert latest_response.json()["window"]["id"] == "window_latest"
        assert latest_response.json()["items"][0]["analysis_result"]["id"] == "analysis_latest"
        assert latest_response.json()["items"][0]["platform_display_name"] == "澎湃新闻"

        history_response = await client.get("/monitor/windows/history", params={"hours": 6})
        assert history_response.status_code == 200
        windows = history_response.json()["windows"]
        assert len(windows) == 1
        assert windows[0]["window"]["id"] == "window_history"
        assert windows[0]["items"][0]["platform_display_name"] == "澎湃新闻"


@pytest.mark.anyio
async def test_monitor_window_item_manual_analyze_endpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from datetime import datetime, timezone

    from app.api import routes_monitor
    from app.schemas.monitor import (
        AnalysisStage,
        MonitorAnalysisResult,
        MonitorScanTriggerType,
        MonitorScanWindow,
        MonitorScanWindowStatus,
        MonitorWindowItem,
    )
    from app.services.monitor.store import (
        create_monitor_scan_window,
        get_monitor_scan_window_detail,
        save_monitor_window_item,
    )

    window = create_monitor_scan_window(
        MonitorScanWindow(
            id="window_manual_analyze",
            window_start=datetime(2026, 3, 21, 16, 0, tzinfo=timezone.utc),
            window_end=datetime(2026, 3, 21, 17, 0, tzinfo=timezone.utc),
            trigger_type=MonitorScanTriggerType.MANUAL,
            status=MonitorScanWindowStatus.COMPLETED,
            platforms=["thepaper"],
        )
    )
    save_monitor_window_item(
        MonitorWindowItem(
            id="window_item_manual_analyze",
            window_id=window.id,
            platform="thepaper",
            hot_item_id="hot_manual_analyze",
            dedupe_key="thepaper::手动检测新闻::https://example.com/manual-analyze",
            title="手动检测新闻",
            url="https://example.com/manual-analyze",
            hot_value=90,
            rank=1,
            trend="new",
        )
    )

    def _fake_process_hot_item(hot_item, config, dedupe_key=None):
        return MonitorAnalysisResult(
            id="analysis_manual_analyze",
            hot_item_id=hot_item.id,
            platform=hot_item.platform,
            source_url=hot_item.url,
            dedupe_key=dedupe_key,
            crawl_status="done",
            current_stage=AnalysisStage.RISK_SNAPSHOT,
            risk_snapshot_score=55,
            risk_snapshot_label="needs_context",
            risk_snapshot_reasons=["已手动触发检测"],
        )

    monkeypatch.setattr(routes_monitor.pipeline_runner, "process_hot_item", _fake_process_hot_item)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/monitor/window-items/window_item_manual_analyze/analyze")

    assert response.status_code == 200
    assert response.json()["analysis_result"]["id"] == "analysis_manual_analyze"
    detail = get_monitor_scan_window_detail(window.id)
    assert detail is not None
    assert detail.items[0].analysis_result_id == "analysis_manual_analyze"
