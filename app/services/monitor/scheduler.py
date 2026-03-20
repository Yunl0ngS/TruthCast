from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from time import perf_counter


def _default_interval_minutes() -> int:
    try:
        return max(1, int(os.getenv("TRUTHCAST_MONITOR_SCAN_INTERVAL_MINUTES", "10")))
    except (TypeError, ValueError):
        return 10


class MonitorScheduler:
    def __init__(
        self,
        hot_items_service,
        alert_engine,
        default_interval_minutes: int | None = None,
        adaptive_mode: bool = True,
        platform_base_intervals: dict[str, int] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.hot_items = hot_items_service
        self.alert_engine = alert_engine
        self.default_interval = default_interval_minutes or _default_interval_minutes()
        self.adaptive_mode = adaptive_mode
        self.platform_base_intervals = dict(platform_base_intervals or {})
        self._sleep = sleep_func
        self._task: asyncio.Task | None = None
        self._running = False
        self.platform_intervals: dict[str, int] = {}
        self.last_scan_at: datetime | None = None
        self.last_scan_summary: dict[str, dict[str, int]] = {}
        self.failure_count = 0
        self.platform_failures: dict[str, int] = {}
        self.last_error: dict[str, str] | None = None
        self.last_scan_duration_ms: int | None = None
        self.platform_durations_ms: dict[str, int] = {}

    @property
    def is_running(self) -> bool:
        return self._running and self._task is not None and not self._task.done()

    async def start(self):
        if self.is_running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="truthcast-monitor-scheduler")

    async def stop(self):
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run_loop(self):
        try:
            while self._running:
                await self.scan_all_platforms()
                await self._sleep(self._current_sleep_minutes() * 60)
        except asyncio.CancelledError:
            raise

    async def scan_all_platforms(self):
        started_at = perf_counter()
        all_items = await self.hot_items.fetch_all()
        self.last_scan_at = datetime.now(timezone.utc)
        for platform, items in all_items.items():
            await self.process_platform(platform, items)
        self.last_scan_duration_ms = int((perf_counter() - started_at) * 1000)

    async def process_platform(self, platform: str, items: list):
        started_at = perf_counter()
        try:
            delta = await self.hot_items.detect_incremental(items, platform)
            await self.hot_items.save(items)
            candidates = delta.get("new", []) + delta.get("updated", [])
            if candidates:
                await self.alert_engine.check_and_alert(candidates, platform)
            self.last_scan_summary[platform] = {
                "fetched": len(items),
                "new": len(delta.get("new", [])),
                "updated": len(delta.get("updated", [])),
                "removed": len(delta.get("removed", [])),
                "alert_candidates": len(candidates),
            }
            if self.adaptive_mode:
                await self.adjust_schedule(platform, candidates)
        except Exception as exc:  # noqa: BLE001
            self.failure_count += 1
            self.platform_failures[platform] = self.platform_failures.get(platform, 0) + 1
            self.last_error = {
                "platform": platform,
                "message": str(exc),
                "at": datetime.now(timezone.utc).isoformat(),
            }
            self.last_scan_summary[platform] = {
                "fetched": len(items),
                "new": 0,
                "updated": 0,
                "removed": 0,
                "alert_candidates": 0,
            }
            if self.adaptive_mode:
                await self.adjust_schedule(platform, [])
        finally:
            self.platform_durations_ms[platform] = int((perf_counter() - started_at) * 1000)

    async def trigger_manual_scan(self, platforms: list[str] | None = None):
        if platforms:
            for platform in platforms:
                items = await self.hot_items.fetch_platform(platform)
                await self.process_platform(platform, items)
            return
        await self.scan_all_platforms()

    async def adjust_schedule(self, platform: str, items: list):
        base_interval = self.platform_base_intervals.get(platform, self.default_interval)
        current_interval = self.platform_intervals.get(platform, base_interval)
        high_risk_count = sum(
            1 for item in items if getattr(item, "risk_score", 0) and getattr(item, "risk_score", 0) >= 70
        )

        if high_risk_count > 0:
            new_interval = max(2, current_interval // 2)
        elif len(items) == 0:
            new_interval = base_interval
        else:
            new_interval = base_interval

        self.platform_intervals[platform] = new_interval

    def _current_sleep_minutes(self) -> int:
        effective_intervals = dict(self.platform_base_intervals)
        effective_intervals.update(self.platform_intervals)
        if not effective_intervals:
            return self.default_interval
        return max(1, min(effective_intervals.values()))

    def get_runtime_status(self) -> dict[str, object]:
        effective_intervals = dict(self.platform_base_intervals)
        effective_intervals.update(self.platform_intervals)
        return {
            "running": self.is_running,
            "adaptive_mode": self.adaptive_mode,
            "default_interval_minutes": self.default_interval,
            "effective_interval_minutes": self._current_sleep_minutes(),
            "platform_intervals": effective_intervals,
            "last_scan_at": self.last_scan_at.isoformat() if self.last_scan_at else None,
            "last_scan_summary": dict(self.last_scan_summary),
            "failure_count": self.failure_count,
            "platform_failures": dict(self.platform_failures),
            "last_error": dict(self.last_error) if self.last_error else None,
            "last_scan_duration_ms": self.last_scan_duration_ms,
            "platform_durations_ms": dict(self.platform_durations_ms),
        }
