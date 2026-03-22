from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from time import perf_counter
from uuid import uuid4

from app.schemas.monitor import (
    MonitorScanTriggerType,
    MonitorScanWindow,
    MonitorScanWindowStatus,
    MonitorWindowItem,
)
from app.services.monitor.dedupe import build_monitor_dedupe_key
from app.services.monitor.platform_config import MonitorPlatformConfig
from app.services.monitor.store import (
    create_monitor_scan_window,
    find_monitor_analysis_result_by_dedupe_key,
    save_monitor_window_item,
    update_monitor_scan_window_counters,
    update_monitor_window_item_analysis_result,
    update_monitor_window_item_analysis_status,
)


def _default_interval_minutes() -> int:
    try:
        return max(1, int(os.getenv("TRUTHCAST_MONITOR_SCAN_INTERVAL_MINUTES", "10")))
    except (TypeError, ValueError):
        return 10


def _manual_scan_auto_analyze_default() -> bool:
    return os.getenv("TRUTHCAST_MONITOR_MANUAL_SCAN_AUTO_ANALYZE", "false").strip().lower() == "true"


def _window_item_id(window_id: str, dedupe_key: str) -> str:
    digest = sha1(f"{window_id}::{dedupe_key}".encode("utf-8")).hexdigest()[:16]
    return f"window_item_{digest}"


class MonitorScheduler:
    def __init__(
        self,
        hot_items_service,
        alert_engine,
        pipeline_runner=None,
        default_interval_minutes: int | None = None,
        adaptive_mode: bool = True,
        platform_base_intervals: dict[str, int] | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now_func: Callable[[], datetime] | None = None,
    ):
        self.hot_items = hot_items_service
        self.alert_engine = alert_engine
        self.pipeline_runner = pipeline_runner
        self.default_interval = default_interval_minutes or _default_interval_minutes()
        self.adaptive_mode = adaptive_mode
        self.platform_base_intervals = dict(platform_base_intervals or {})
        self._sleep = sleep_func
        self._now = now_func or (lambda: datetime.now(timezone.utc))
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
        self._active_window = None
        self._active_metrics = None
        self._background_analysis_tasks: set[asyncio.Task] = set()

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
        self.last_scan_at = self._now()
        window = self._create_window(
            list(all_items.keys()),
            trigger_type=MonitorScanTriggerType.SCHEDULED,
        )
        metrics = {
            "fetched_count": 0,
            "deduplicated_count": 0,
            "analyzed_count": 0,
            "duplicate_count": 0,
            "seen_keys": set(),
        }
        self._active_window = window
        self._active_metrics = metrics
        pending_by_platform: dict[str, list[tuple[object, MonitorPlatformConfig, str]]] = {}
        for platform, items in all_items.items():
            pending_items = await self.process_platform(platform, items)
            if pending_items:
                pending_by_platform[platform] = pending_items
        create_monitor_scan_window(
            window.model_copy(
                update={
                    "status": MonitorScanWindowStatus.COMPLETED,
                    "fetched_count": metrics["fetched_count"],
                    "deduplicated_count": metrics["deduplicated_count"],
                    "analyzed_count": metrics["analyzed_count"],
                    "duplicate_count": metrics["duplicate_count"],
                    "updated_at": self._now(),
                }
            )
        )
        self._active_window = None
        self._active_metrics = None
        self.last_scan_duration_ms = int((perf_counter() - started_at) * 1000)
        if pending_by_platform:
            task = asyncio.create_task(
                self._run_background_analysis(window.id, pending_by_platform),
                name=f"truthcast-monitor-scheduled-analysis-{window.id}",
            )
            self._background_analysis_tasks.add(task)
            task.add_done_callback(self._background_analysis_tasks.discard)

    async def process_platform(self, platform: str, items: list) -> list[tuple[object, MonitorPlatformConfig, str]]:
        started_at = perf_counter()
        config = None
        window = self._active_window
        metrics = self._active_metrics
        pending: list[tuple[object, MonitorPlatformConfig, str]] = []
        try:
            delta = await self.hot_items.detect_incremental(items, platform)
            await self.hot_items.save(items)
            candidates = delta.get("new", []) + delta.get("updated", [])
            candidate_ids = {item.id for item in candidates}
            if candidates:
                await self.alert_engine.check_and_alert(candidates, platform)
                if self.pipeline_runner is not None:
                    config = next(
                        (
                            item
                            for item in getattr(self.hot_items, "platform_configs", [])
                            if getattr(item, "key", None) == platform
                        ),
                        None,
                    )
                    if config is None:
                        config = MonitorPlatformConfig(
                            key=platform,
                            display_name=platform,
                            newsnow_id=platform,
                            enabled=True,
                            scan_interval_minutes=self.platform_base_intervals.get(
                                platform, self.default_interval
                            ),
                        )
            if metrics is not None:
                metrics["fetched_count"] += len(items)
            if window is not None:
                pending = await self._record_window_items(window, platform, items, config, metrics, candidate_ids)
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
        return pending

    def _platform_config_for(self, platform: str) -> MonitorPlatformConfig:
        config = next(
            (
                item
                for item in getattr(self.hot_items, "platform_configs", [])
                if getattr(item, "key", None) == platform
            ),
            None,
        )
        if config is not None:
            return config
        return MonitorPlatformConfig(
            key=platform,
            display_name=platform,
            newsnow_id=platform,
            enabled=True,
            scan_interval_minutes=self.platform_base_intervals.get(platform, self.default_interval),
        )

    async def trigger_manual_scan(
        self,
        platforms: list[str] | None = None,
        auto_analyze: bool | None = None,
    ) -> dict[str, object]:
        resolved_auto_analyze = (
            _manual_scan_auto_analyze_default() if auto_analyze is None else auto_analyze
        )
        trigger_type = MonitorScanTriggerType.MANUAL
        grouped = (
            {platform: await self.hot_items.fetch_platform(platform) for platform in platforms}
            if platforms
            else await self.hot_items.fetch_all()
        )
        scanned_platforms = list(grouped.keys())
        window = self._create_window(scanned_platforms, trigger_type=trigger_type)
        metrics = {
            "fetched_count": 0,
            "deduplicated_count": 0,
            "analyzed_count": 0,
            "duplicate_count": 0,
            "seen_keys": set(),
        }
        pending_by_platform: dict[str, list[tuple[object, MonitorPlatformConfig, str]]] = {}
        saved_count = 0
        for platform, items in grouped.items():
            pending_items = await self._process_manual_platform(window, platform, items, metrics)
            saved_count += len(items)
            if pending_items:
                pending_by_platform[platform] = pending_items
        create_monitor_scan_window(
            window.model_copy(
                update={
                    "status": MonitorScanWindowStatus.COMPLETED,
                    "fetched_count": metrics["fetched_count"],
                    "deduplicated_count": metrics["deduplicated_count"],
                    "analyzed_count": metrics["analyzed_count"],
                    "duplicate_count": metrics["duplicate_count"],
                    "updated_at": self._now(),
                }
            )
        )
        analysis_scheduled = resolved_auto_analyze and any(pending_by_platform.values())
        if analysis_scheduled:
            task = asyncio.create_task(
                self._run_background_analysis(window.id, pending_by_platform),
                name=f"truthcast-monitor-manual-analysis-{window.id}",
            )
            self._background_analysis_tasks.add(task)
            task.add_done_callback(self._background_analysis_tasks.discard)
        return {
            "scanned_platforms": scanned_platforms,
            "saved_count": saved_count,
            "total_fetched": metrics["fetched_count"],
            "window_id": window.id,
            "auto_analyze": resolved_auto_analyze,
            "analysis_scheduled": analysis_scheduled,
        }

    def _window_bounds(self) -> tuple[datetime, datetime]:
        now = self._now()
        window_end = now.replace(minute=0, second=0, microsecond=0)
        window_start = window_end - timedelta(hours=1)
        return window_start, window_end

    def _create_window(self, platforms: list[str], *, trigger_type: MonitorScanTriggerType) -> MonitorScanWindow:
        window_start, window_end = self._window_bounds()
        return create_monitor_scan_window(
            MonitorScanWindow(
                id=f"window_{window_start.strftime('%Y%m%d%H')}",
                window_start=window_start,
                window_end=window_end,
                trigger_type=trigger_type,
                status=MonitorScanWindowStatus.RUNNING,
                platforms=platforms,
                updated_at=self._now(),
            )
        )

    async def _process_manual_platform(self, window, platform: str, items: list, metrics) -> list[tuple[object, MonitorPlatformConfig, str]]:
        started_at = perf_counter()
        pending: list[tuple[object, MonitorPlatformConfig, str]] = []
        try:
            delta = await self.hot_items.detect_incremental(items, platform)
            await self.hot_items.save(items)
            candidate_ids = {item.id for item in (delta.get("new", []) + delta.get("updated", []))}
            config = self._platform_config_for(platform)
            if metrics is not None:
                metrics["fetched_count"] += len(items)
            seen_keys = metrics["seen_keys"] if metrics is not None else set()
            for item in items:
                dedupe_key = build_monitor_dedupe_key(
                    platform,
                    getattr(item, "title", ""),
                    getattr(item, "url", ""),
                )
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                if metrics is not None:
                    metrics["deduplicated_count"] += 1
                existing_analysis = find_monitor_analysis_result_by_dedupe_key(dedupe_key)
                if existing_analysis is not None and metrics is not None:
                    metrics["duplicate_count"] += 1
                save_monitor_window_item(
                    MonitorWindowItem(
                        id=_window_item_id(window.id, dedupe_key),
                        window_id=window.id,
                        platform=platform,
                        hot_item_id=getattr(item, "id", None),
                        analysis_result_id=existing_analysis.id if existing_analysis is not None else None,
                        duplicate_of_analysis_result_id=existing_analysis.id if existing_analysis is not None else None,
                        dedupe_key=dedupe_key,
                        title=getattr(item, "title", ""),
                        url=getattr(item, "url", ""),
                        hot_value=getattr(item, "hot_value", 0),
                        rank=getattr(item, "rank", 0),
                        trend=getattr(item, "trend", "new"),
                        is_duplicate_across_windows=existing_analysis is not None,
                    )
                )
                if existing_analysis is None and getattr(item, "id", None) in candidate_ids:
                    pending.append((item, config, dedupe_key))
            self.last_scan_summary[platform] = {
                "fetched": len(items),
                "new": len(delta.get("new", [])),
                "updated": len(delta.get("updated", [])),
                "removed": len(delta.get("removed", [])),
                "alert_candidates": len(candidate_ids),
            }
            if self.adaptive_mode:
                await self.adjust_schedule(platform, [])
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
        return pending

    async def _run_background_analysis(
        self,
        window_id: str,
        pending_by_platform: dict[str, list[tuple[object, MonitorPlatformConfig, str]]],
    ) -> None:
        analyzed_increment = 0
        duplicate_increment = 0
        for platform, entries in pending_by_platform.items():
            candidates = [item for item, _config, _dedupe_key in entries]
            if candidates:
                await self.alert_engine.check_and_alert(candidates, platform)
            for item, config, dedupe_key in entries:
                existing_analysis = find_monitor_analysis_result_by_dedupe_key(dedupe_key)
                if existing_analysis is not None:
                    duplicate_increment += 1
                    update_monitor_window_item_analysis_result(
                        window_id=window_id,
                        dedupe_key=dedupe_key,
                        analysis_result_id=existing_analysis.id,
                        analysis_status="done",
                        is_duplicate_across_windows=True,
                        duplicate_of_analysis_result_id=existing_analysis.id,
                    )
                    continue
                if self.pipeline_runner is None:
                    continue
                update_monitor_window_item_analysis_status(
                    window_id=window_id,
                    dedupe_key=dedupe_key,
                    analysis_status="running",
                )
                try:
                    analysis_result = await asyncio.to_thread(
                        self.pipeline_runner.process_hot_item,
                        item,
                        config,
                        dedupe_key=dedupe_key,
                    )
                except TypeError:
                    analysis_result = await asyncio.to_thread(self.pipeline_runner.process_hot_item, item, config)
                except Exception:  # noqa: BLE001
                    update_monitor_window_item_analysis_status(
                        window_id=window_id,
                        dedupe_key=dedupe_key,
                        analysis_status="failed",
                    )
                    continue
                if analysis_result is None:
                    update_monitor_window_item_analysis_status(
                        window_id=window_id,
                        dedupe_key=dedupe_key,
                        analysis_status="pending",
                    )
                    continue
                analyzed_increment += 1
                update_monitor_window_item_analysis_result(
                    window_id=window_id,
                    dedupe_key=dedupe_key,
                    analysis_result_id=analysis_result.id,
                    analysis_status="done",
                )
        if analyzed_increment or duplicate_increment:
            update_monitor_scan_window_counters(
                window_id,
                analyzed_increment=analyzed_increment,
                duplicate_increment=duplicate_increment,
            )

    async def _record_window_items(self, window, platform: str, items: list, config, metrics, candidate_ids: set[str]) -> list[tuple[object, MonitorPlatformConfig, str]]:
        seen_keys = metrics["seen_keys"] if metrics is not None else set()
        pending: list[tuple[object, MonitorPlatformConfig, str]] = []
        for item in items:
            dedupe_key = build_monitor_dedupe_key(platform, getattr(item, "title", ""), getattr(item, "url", ""))
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            if metrics is not None:
                metrics["deduplicated_count"] += 1

            existing_analysis = find_monitor_analysis_result_by_dedupe_key(dedupe_key)
            is_duplicate = existing_analysis is not None
            analysis_status = "pending"
            if existing_analysis is not None:
                if metrics is not None:
                    metrics["duplicate_count"] += 1
                analysis_status = "done"
            elif (
                self.pipeline_runner is not None
                and config is not None
                and getattr(item, "id", None) in candidate_ids
            ):
                pending.append((item, config, dedupe_key))

            save_monitor_window_item(
                MonitorWindowItem(
                    id=_window_item_id(window.id, dedupe_key),
                    window_id=window.id,
                    platform=platform,
                    hot_item_id=getattr(item, "id", None),
                    analysis_result_id=existing_analysis.id if existing_analysis is not None else None,
                    duplicate_of_analysis_result_id=existing_analysis.id if existing_analysis is not None else None,
                    analysis_status=analysis_status,
                    dedupe_key=dedupe_key,
                    title=getattr(item, "title", ""),
                    url=getattr(item, "url", ""),
                    hot_value=getattr(item, "hot_value", 0),
                    rank=getattr(item, "rank", 0),
                    trend=getattr(item, "trend", "new"),
                    is_duplicate_across_windows=is_duplicate,
                )
            )
        return pending

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
        enabled_platforms = [
            {
                "key": item.key,
                "display_name": item.display_name,
            }
            for item in getattr(self.hot_items, "platform_configs", [])
        ]
        return {
            "running": self.is_running,
            "adaptive_mode": self.adaptive_mode,
            "manual_scan_auto_analyze_default": _manual_scan_auto_analyze_default(),
            "enabled_platforms": enabled_platforms,
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
