from __future__ import annotations

import asyncio

import pytest

from app.schemas.monitor import HotItem, TrendDirection


@pytest.mark.anyio
async def test_monitor_scheduler_trigger_manual_scan_returns_window_scan_result(monkeypatch) -> None:
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

        async def detect_incremental(self, items, platform):
            return {"new": items, "updated": [], "removed": []}

        async def save(self, items):
            return len(items)

    scheduler = MonitorScheduler(hot_items_service=_HotItems(), alert_engine=object())

    result = await scheduler.trigger_manual_scan(["weibo", "zhihu"], auto_analyze=False)

    assert result["scanned_platforms"] == ["weibo", "zhihu"]
    assert result["saved_count"] == 2
    assert result["total_fetched"] == 2
    assert result["auto_analyze"] is False
    assert result["analysis_scheduled"] is False


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


@pytest.mark.anyio
async def test_scheduler_dispatches_pipeline_runner_after_scan() -> None:
    from app.services.monitor.scheduler import MonitorScheduler

    class _HotItems:
        async def fetch_all(self):
            return {
                "thepaper": [
                    HotItem(
                        id="thepaper_1",
                        platform="thepaper",
                        title="澎湃新闻热点",
                        url="https://example.com/thepaper/1",
                        hot_value=100,
                        rank=1,
                        trend=TrendDirection.NEW,
                    )
                ]
            }

        async def detect_incremental(self, items, platform):
            return {"new": items, "updated": [], "removed": []}

        async def save(self, items):
            return len(items)

    class _AlertEngine:
        async def check_and_alert(self, items, platform):
            return []

    captured: list[tuple[str, str]] = []

    class _PipelineRunner:
        def process_hot_item(self, item, config):
            captured.append((item.id, config.key))
            return None

    scheduler = MonitorScheduler(
        hot_items_service=_HotItems(),
        alert_engine=_AlertEngine(),
        pipeline_runner=_PipelineRunner(),
    )

    await scheduler.scan_all_platforms()
    if scheduler._background_analysis_tasks:
        await asyncio.gather(*scheduler._background_analysis_tasks)

    assert captured == [("thepaper_1", "thepaper")]


@pytest.mark.anyio
async def test_scheduler_creates_hourly_window_and_window_items(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from app.services.monitor.scheduler import MonitorScheduler
    from app.services.monitor.store import list_monitor_scan_window_details

    class _HotItems:
        platform_configs = []

        async def fetch_all(self):
            return {
                "thepaper": [
                    HotItem(
                        id="thepaper_window_1",
                        platform="thepaper",
                        title="窗口新闻",
                        url="https://example.com/window/1",
                        hot_value=120,
                        rank=1,
                        trend=TrendDirection.NEW,
                    )
                ]
            }

        async def detect_incremental(self, items, platform):
            return {"new": items, "updated": [], "removed": []}

        async def save(self, items):
            return len(items)

    class _AlertEngine:
        async def check_and_alert(self, items, platform):
            return []

    class _PipelineRunner:
        def process_hot_item(self, item, config, dedupe_key=None):
            from app.schemas.monitor import AnalysisStage, MonitorAnalysisResult

            return MonitorAnalysisResult(
                id="analysis_window_1",
                hot_item_id=item.id,
                platform=item.platform,
                source_url=item.url,
                dedupe_key=dedupe_key,
                crawl_status="done",
                current_stage=AnalysisStage.RISK_SNAPSHOT,
                risk_snapshot_score=44,
                risk_snapshot_label="needs_context",
                risk_snapshot_reasons=["窗口抓取成功"],
            )

    scheduler = MonitorScheduler(
        hot_items_service=_HotItems(),
        alert_engine=_AlertEngine(),
        pipeline_runner=_PipelineRunner(),
        now_func=lambda: __import__("datetime").datetime(2026, 3, 21, 17, 28, tzinfo=__import__("datetime").timezone.utc),
    )

    await scheduler.scan_all_platforms()

    details = list_monitor_scan_window_details(limit=5)
    assert len(details) == 1
    assert details[0].window.window_start.isoformat() == "2026-03-21T16:00:00+00:00"
    assert details[0].window.window_end.isoformat() == "2026-03-21T17:00:00+00:00"
    assert details[0].window.fetched_count == 1
    assert len(details[0].items) == 1
    assert details[0].items[0].analysis_status == "pending"
    assert details[0].items[0].analysis_result_id is None

    if scheduler._background_analysis_tasks:
        await asyncio.gather(*scheduler._background_analysis_tasks)

    details = list_monitor_scan_window_details(limit=5)
    assert details[0].window.analyzed_count == 1
    assert details[0].items[0].analysis_status == "done"
    assert details[0].items[0].analysis_result_id == "analysis_window_1"


@pytest.mark.anyio
async def test_scheduler_skips_duplicate_analysis_across_windows(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from datetime import datetime, timezone

    from app.schemas.monitor import AnalysisStage, MonitorAnalysisResult
    from app.services.monitor.scheduler import MonitorScheduler
    from app.services.monitor.store import list_monitor_scan_window_details, save_monitor_analysis_result

    save_monitor_analysis_result(
        MonitorAnalysisResult(
            id="analysis_existing",
            hot_item_id="hot_existing",
            platform="thepaper",
            source_url="https://example.com/repeat",
            dedupe_key="thepaper::重复新闻::https://example.com/repeat",
            crawl_status="done",
            current_stage=AnalysisStage.REPORT,
            risk_snapshot_score=68,
            risk_snapshot_label="high_risk",
            risk_snapshot_reasons=["已存在历史研判"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )

    class _HotItems:
        platform_configs = []

        async def fetch_all(self):
            return {
                "thepaper": [
                    HotItem(
                        id="thepaper_repeat_1",
                        platform="thepaper",
                        title="重复新闻",
                        url="https://example.com/repeat",
                        hot_value=140,
                        rank=1,
                        trend=TrendDirection.NEW,
                    )
                ]
            }

        async def detect_incremental(self, items, platform):
            return {"new": items, "updated": [], "removed": []}

        async def save(self, items):
            return len(items)

    class _AlertEngine:
        async def check_and_alert(self, items, platform):
            return []

    captured: list[str] = []

    class _PipelineRunner:
        def process_hot_item(self, item, config, dedupe_key=None):
            captured.append(item.id)
            raise AssertionError("重复新闻不应再次进入检测")

    scheduler = MonitorScheduler(
        hot_items_service=_HotItems(),
        alert_engine=_AlertEngine(),
        pipeline_runner=_PipelineRunner(),
        now_func=lambda: __import__("datetime").datetime(2026, 3, 21, 18, 28, tzinfo=__import__("datetime").timezone.utc),
    )

    await scheduler.scan_all_platforms()

    details = list_monitor_scan_window_details(limit=5)
    assert details[0].window.duplicate_count == 1
    assert details[0].window.analyzed_count == 0
    assert details[0].items[0].is_duplicate_across_windows is True
    assert details[0].items[0].analysis_result_id == "analysis_existing"
    assert captured == []


@pytest.mark.anyio
async def test_scheduler_does_not_duplicate_window_items_within_same_manual_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))

    from datetime import datetime, timezone

    from app.services.monitor.scheduler import MonitorScheduler
    from app.services.monitor.store import get_monitor_scan_window_detail

    class _HotItems:
        platform_configs = []

        async def fetch_platform(self, platform: str):
            return [
                HotItem(
                    id="thepaper_repeat_same_window",
                    platform=platform,
                    title="同一窗口重复刷新新闻",
                    url="https://example.com/same-window",
                    hot_value=88,
                    rank=1,
                    trend=TrendDirection.NEW,
                )
            ]

        async def detect_incremental(self, items, platform):
            return {"new": [], "updated": [], "removed": []}

        async def save(self, items):
            return len(items)

    scheduler = MonitorScheduler(
        hot_items_service=_HotItems(),
        alert_engine=object(),
        now_func=lambda: datetime(2026, 3, 21, 17, 28, tzinfo=timezone.utc),
    )

    await scheduler.trigger_manual_scan(["thepaper"], auto_analyze=False)
    await scheduler.trigger_manual_scan(["thepaper"], auto_analyze=False)

    detail = get_monitor_scan_window_detail("window_2026032116")
    assert detail is not None
    assert len(detail.items) == 1
    assert detail.items[0].title == "同一窗口重复刷新新闻"
