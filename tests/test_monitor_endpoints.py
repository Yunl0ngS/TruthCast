import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


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
async def test_monitor_scan_triggers_alert_checks(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

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
        response = await client.post("/monitor/scan", json={})
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
        assert body["last_scan_summary"]["weibo"]["alert_candidates"] == 1
        assert body["failure_count"] == 2
        assert body["last_error"]["platform"] == "zhihu"
        assert body["last_scan_duration_ms"] == 842
        assert body["platform_durations_ms"]["weibo"] == 320
