from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from app.schemas.monitor import HotItem, TrendDirection


@pytest.mark.anyio
async def test_monitor_scheduler_trigger_manual_scan_processes_platforms(monkeypatch) -> None:
    from app.services.monitor.scheduler import MonitorScheduler

    class _HotItems:
        async def fetch_platform(self, platform: str):
            return [
                HotItem(
                    id=f"{platform}_1",
                    platform=platform,
                    title=f"{platform} 热点",
                    url=f"https://example.com/{platform}",
                    hot_value=100,
                    rank=1,
                    trend=TrendDirection.NEW,
                )
            ]

    processed: list[tuple[str, list[str]]] = []

    class _Scheduler(MonitorScheduler):
        async def process_platform(self, platform: str, items: list[HotItem]):
            processed.append((platform, [item.id for item in items]))

    scheduler = _Scheduler(hot_items_service=_HotItems(), alert_engine=object())

    await scheduler.trigger_manual_scan(["weibo", "zhihu"])

    assert processed == [
        ("weibo", ["weibo_1"]),
        ("zhihu", ["zhihu_1"]),
    ]


@pytest.mark.anyio
async def test_lifespan_starts_and_stops_monitor_scheduler(monkeypatch) -> None:
    import app.main as main_module

    events: list[str] = []

    class _FakeScheduler:
        async def start(self):
            events.append("start")

        async def stop(self):
            events.append("stop")

    monkeypatch.setenv("TRUTHCAST_MONITOR_ENABLED", "true")
    monkeypatch.setattr(main_module, "monitor_scheduler", _FakeScheduler())
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(main_module, "init_chat_db", lambda: None)
    monkeypatch.setattr(main_module, "init_monitor_db", lambda: None)
    monkeypatch.setattr(main_module, "init_semaphore", lambda: None)

    async with main_module.lifespan(main_module.app):
        assert events == ["start"]

    assert events == ["start", "stop"]


@pytest.mark.anyio
async def test_monitor_scheduler_adjusts_interval_by_risk_signal() -> None:
    from app.schemas.monitor import HotItem, TrendDirection
    from app.services.monitor.scheduler import MonitorScheduler

    scheduler = MonitorScheduler(
        hot_items_service=object(),
        alert_engine=object(),
        default_interval_minutes=10,
        adaptive_mode=True,
    )

    high_risk_items = [
        HotItem(
            id="risk_1",
            platform="weibo",
            title="高风险热点",
            url="https://example.com/risk",
            hot_value=500,
            rank=1,
            trend=TrendDirection.RISING,
            risk_score=88,
            risk_level="high_risk",
        )
    ]

    await scheduler.adjust_schedule("weibo", high_risk_items)
    assert scheduler.get_runtime_status()["platform_intervals"]["weibo"] == 5

    await scheduler.adjust_schedule("weibo", [])
    assert scheduler.get_runtime_status()["platform_intervals"]["weibo"] == 10


@pytest.mark.anyio
async def test_monitor_scheduler_uses_platform_base_interval_when_configured() -> None:
    from app.services.monitor.scheduler import MonitorScheduler

    scheduler = MonitorScheduler(
        hot_items_service=object(),
        alert_engine=object(),
        default_interval_minutes=10,
        adaptive_mode=True,
        platform_base_intervals={"weibo": 6, "zhihu": 15},
    )

    await scheduler.adjust_schedule("weibo", [])
    await scheduler.adjust_schedule("zhihu", [])

    status = scheduler.get_runtime_status()
    assert status["platform_intervals"]["weibo"] == 6
    assert status["platform_intervals"]["zhihu"] == 15


@pytest.mark.anyio
async def test_monitor_scheduler_tracks_failure_error_and_duration() -> None:
    from app.services.monitor.scheduler import MonitorScheduler

    class _BrokenHotItems:
        async def fetch_all(self):
            return {"weibo": ["bad-item"]}

        async def detect_incremental(self, items, platform):
            raise RuntimeError(f"{platform} fetch timeout")

        async def save(self, items):
            return 0

    class _AlertEngine:
        async def check_and_alert(self, items, platform):
            return []

    scheduler = MonitorScheduler(
        hot_items_service=_BrokenHotItems(),
        alert_engine=_AlertEngine(),
        default_interval_minutes=10,
        adaptive_mode=True,
    )

    await scheduler.scan_all_platforms()

    status = scheduler.get_runtime_status()
    assert status["failure_count"] == 1
    assert status["platform_failures"]["weibo"] == 1
    assert status["last_error"]["platform"] == "weibo"
    assert "timeout" in status["last_error"]["message"]
    assert status["last_scan_duration_ms"] >= 0
    assert "weibo" in status["platform_durations_ms"]
