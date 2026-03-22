from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from app.schemas.monitor import (
    AnalysisStage,
    MonitorAnalysisResult,
    MonitorScanTriggerType,
    MonitorScanWindow,
    MonitorScanWindowDetail,
    MonitorScanWindowHistoryResponse,
    MonitorScanWindowStatus,
    MonitorWindowItem,
    MonitorWindowItemView,
)
from app.services.monitor.platform_config import load_monitor_platforms


DB_PATH = Path("data/monitor/monitor.db")
_active_db_path: Path | None = None


def _default_db_path() -> Path:
    custom_path = os.getenv("TRUTHCAST_MONITOR_DB_PATH", "").strip()
    if custom_path:
        return Path(custom_path)
    return DB_PATH


def _fallback_db_path() -> Path:
    return Path(tempfile.gettempdir()) / "truthcast" / "monitor.db"


def _is_disk_io_error(exc: sqlite3.OperationalError) -> bool:
    return "disk i/o error" in str(exc).lower()


def _get_active_db_path() -> Path:
    custom_path = os.getenv("TRUTHCAST_MONITOR_DB_PATH", "").strip()
    if custom_path:
        return Path(custom_path)
    return _active_db_path or DB_PATH


def _set_fallback_db_path() -> Path:
    global _active_db_path
    _active_db_path = _fallback_db_path()
    return _active_db_path


def _create_tables(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_subscriptions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                keywords_json TEXT NOT NULL,
                match_mode TEXT NOT NULL,
                platforms_json TEXT NOT NULL,
                exclude_keywords_json TEXT NOT NULL,
                trigger_mode TEXT NOT NULL,
                risk_threshold INTEGER NOT NULL,
                smart_threshold_json TEXT NOT NULL,
                notify_channels_json TEXT NOT NULL,
                notify_config_json TEXT NOT NULL,
                notify_template TEXT,
                quiet_hours_json TEXT,
                is_active INTEGER NOT NULL,
                priority INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_hot_items (
                id TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                summary TEXT,
                cover_image TEXT,
                hot_value INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                trend TEXT NOT NULL,
                risk_score INTEGER,
                risk_level TEXT,
                risk_assessed_at TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                last_hot_value INTEGER NOT NULL,
                extra_json TEXT NOT NULL,
                raw_data_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_alerts (
                id TEXT PRIMARY KEY,
                hot_item_id TEXT NOT NULL,
                trigger_reason TEXT NOT NULL,
                trigger_mode TEXT NOT NULL,
                matched_subscriptions_json TEXT NOT NULL,
                matched_keywords_json TEXT NOT NULL,
                risk_score INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                risk_summary TEXT,
                hot_item_title TEXT NOT NULL,
                hot_item_url TEXT NOT NULL,
                hot_item_platform TEXT NOT NULL,
                hot_item_hot_value INTEGER NOT NULL,
                hot_item_rank INTEGER NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                notify_channels_json TEXT NOT NULL,
                notify_results_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                cooldown_until TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_analysis_results (
                id TEXT PRIMARY KEY,
                hot_item_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                source_url TEXT NOT NULL,
                dedupe_key TEXT,
                history_record_id TEXT,
                crawl_status TEXT NOT NULL,
                crawl_title TEXT,
                crawl_content TEXT,
                crawl_publish_date TEXT,
                risk_snapshot_score INTEGER,
                risk_snapshot_label TEXT,
                risk_snapshot_reasons_json TEXT NOT NULL DEFAULT '[]',
                raw_evidences_json TEXT NOT NULL DEFAULT '[]',
                evidences_json TEXT NOT NULL DEFAULT '[]',
                current_stage TEXT NOT NULL,
                report_score INTEGER,
                report_level TEXT,
                report_data_json TEXT,
                simulation_status TEXT NOT NULL,
                simulation_data_json TEXT,
                content_generation_status TEXT NOT NULL,
                content_data_json TEXT,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_scan_windows (
                id TEXT PRIMARY KEY,
                window_start TEXT NOT NULL,
                window_end TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL,
                platforms_json TEXT NOT NULL,
                fetched_count INTEGER NOT NULL,
                deduplicated_count INTEGER NOT NULL,
                analyzed_count INTEGER NOT NULL,
                duplicate_count INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monitor_window_items (
                id TEXT PRIMARY KEY,
                window_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                hot_item_id TEXT,
                analysis_result_id TEXT,
                duplicate_of_analysis_result_id TEXT,
                analysis_status TEXT NOT NULL DEFAULT 'pending',
                dedupe_key TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                hot_value INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                trend TEXT NOT NULL,
                is_duplicate_across_windows INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        _deduplicate_monitor_window_items(conn)
        _ensure_monitor_window_item_columns(conn)
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_monitor_window_items_window_dedupe
            ON monitor_window_items(window_id, dedupe_key)
            """
        )
        _ensure_monitor_analysis_result_columns(conn)
        conn.commit()


def _ensure_monitor_analysis_result_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(monitor_analysis_results)").fetchall()
    columns = {row[1] for row in rows}
    column_defs = {
        "dedupe_key": "TEXT",
        "history_record_id": "TEXT",
        "crawl_title": "TEXT",
        "crawl_content": "TEXT",
        "crawl_publish_date": "TEXT",
        "risk_snapshot_score": "INTEGER",
        "risk_snapshot_label": "TEXT",
        "risk_snapshot_reasons_json": "TEXT NOT NULL DEFAULT '[]'",
        "raw_evidences_json": "TEXT NOT NULL DEFAULT '[]'",
        "evidences_json": "TEXT NOT NULL DEFAULT '[]'",
        "current_stage": "TEXT NOT NULL DEFAULT 'hot_item'",
        "report_score": "INTEGER",
        "report_level": "TEXT",
        "report_data_json": "TEXT",
        "simulation_status": "TEXT NOT NULL DEFAULT 'pending'",
        "simulation_data_json": "TEXT",
        "content_generation_status": "TEXT NOT NULL DEFAULT 'idle'",
        "content_data_json": "TEXT",
        "last_error": "TEXT",
    }
    for name, definition in column_defs.items():
        if name in columns:
            continue
        conn.execute(
            f"ALTER TABLE monitor_analysis_results ADD COLUMN {name} {definition}"
        )


def _ensure_monitor_window_item_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute("PRAGMA table_info(monitor_window_items)").fetchall()
    columns = {row[1] for row in rows}
    column_defs = {
        "analysis_status": "TEXT NOT NULL DEFAULT 'pending'",
    }
    for name, definition in column_defs.items():
        if name in columns:
            continue
        conn.execute(
            f"ALTER TABLE monitor_window_items ADD COLUMN {name} {definition}"
        )


def _deduplicate_monitor_window_items(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM monitor_window_items
        WHERE rowid NOT IN (
            SELECT MAX(rowid)
            FROM monitor_window_items
            GROUP BY window_id, dedupe_key
        )
        """
    )


def init_monitor_db() -> None:
    db_path = _get_active_db_path()
    try:
        _create_tables(db_path)
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        _create_tables(fallback)


@contextmanager
def monitor_connection() -> Iterator[sqlite3.Connection]:
    init_monitor_db()
    db_path = _get_active_db_path()
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn
    except sqlite3.OperationalError as exc:
        if not _is_disk_io_error(exc):
            raise
        fallback = _set_fallback_db_path()
        _create_tables(fallback)
        with sqlite3.connect(fallback) as conn:
            conn.row_factory = sqlite3.Row
            yield conn


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _platform_display_name_map() -> dict[str, str]:
    return {item.key: item.display_name for item in load_monitor_platforms()}


def _row_to_monitor_analysis_result(row: sqlite3.Row | None) -> MonitorAnalysisResult | None:
    if row is None:
        return None
    return MonitorAnalysisResult(
        id=row["id"],
        hot_item_id=row["hot_item_id"],
        platform=row["platform"],
        source_url=row["source_url"],
        dedupe_key=row["dedupe_key"],
        history_record_id=row["history_record_id"],
        crawl_status=row["crawl_status"],
        crawl_title=row["crawl_title"],
        crawl_content=row["crawl_content"],
        crawl_publish_date=row["crawl_publish_date"],
        risk_snapshot_score=row["risk_snapshot_score"],
        risk_snapshot_label=row["risk_snapshot_label"],
        risk_snapshot_reasons=json.loads(row["risk_snapshot_reasons_json"])
        if row["risk_snapshot_reasons_json"]
        else [],
        raw_evidences=json.loads(row["raw_evidences_json"]) if row["raw_evidences_json"] else [],
        evidences=json.loads(row["evidences_json"]) if row["evidences_json"] else [],
        current_stage=AnalysisStage(row["current_stage"]),
        report_score=row["report_score"],
        report_level=row["report_level"],
        report_data=json.loads(row["report_data_json"]) if row["report_data_json"] else None,
        simulation_status=row["simulation_status"],
        simulation_data=json.loads(row["simulation_data_json"]) if row["simulation_data_json"] else None,
        content_generation_status=row["content_generation_status"],
        content_data=json.loads(row["content_data_json"]) if row["content_data_json"] else None,
        last_error=row["last_error"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def save_monitor_analysis_result(result: MonitorAnalysisResult) -> MonitorAnalysisResult:
    now = _utc_now().isoformat()
    created_at = result.created_at.isoformat() if result.created_at else now
    updated_at = result.updated_at.isoformat() if result.updated_at else now
    with monitor_connection() as conn:
        conn.execute(
            """
            INSERT INTO monitor_analysis_results (
                id, hot_item_id, platform, source_url, crawl_status, crawl_title, crawl_content,
                dedupe_key, history_record_id, crawl_publish_date, risk_snapshot_score, risk_snapshot_label, risk_snapshot_reasons_json,
                raw_evidences_json, evidences_json, current_stage,
                report_score, report_level, report_data_json, simulation_status, simulation_data_json,
                content_generation_status, content_data_json, last_error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                hot_item_id = excluded.hot_item_id,
                platform = excluded.platform,
                source_url = excluded.source_url,
                dedupe_key = excluded.dedupe_key,
                history_record_id = excluded.history_record_id,
                crawl_status = excluded.crawl_status,
                crawl_title = excluded.crawl_title,
                crawl_content = excluded.crawl_content,
                crawl_publish_date = excluded.crawl_publish_date,
                risk_snapshot_score = excluded.risk_snapshot_score,
                risk_snapshot_label = excluded.risk_snapshot_label,
                risk_snapshot_reasons_json = excluded.risk_snapshot_reasons_json,
                raw_evidences_json = excluded.raw_evidences_json,
                evidences_json = excluded.evidences_json,
                current_stage = excluded.current_stage,
                report_score = excluded.report_score,
                report_level = excluded.report_level,
                report_data_json = excluded.report_data_json,
                simulation_status = excluded.simulation_status,
                simulation_data_json = excluded.simulation_data_json,
                content_generation_status = excluded.content_generation_status,
                content_data_json = excluded.content_data_json,
                last_error = excluded.last_error,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                result.id,
                result.hot_item_id,
                result.platform,
                result.source_url,
                result.crawl_status,
                result.crawl_title,
                result.crawl_content,
                result.dedupe_key,
                result.history_record_id,
                result.crawl_publish_date,
                result.risk_snapshot_score,
                result.risk_snapshot_label,
                json.dumps(result.risk_snapshot_reasons, ensure_ascii=False),
                json.dumps(result.raw_evidences, ensure_ascii=False),
                json.dumps(result.evidences, ensure_ascii=False),
                result.current_stage.value,
                result.report_score,
                result.report_level,
                json.dumps(result.report_data, ensure_ascii=False) if result.report_data is not None else None,
                result.simulation_status,
                json.dumps(result.simulation_data, ensure_ascii=False) if result.simulation_data is not None else None,
                result.content_generation_status,
                json.dumps(result.content_data.model_dump(), ensure_ascii=False) if result.content_data is not None else None,
                result.last_error,
                created_at,
                updated_at,
            ),
        )
        conn.commit()
    return result.model_copy(
        update={
            "created_at": datetime.fromisoformat(created_at),
            "updated_at": datetime.fromisoformat(updated_at),
        }
    )


def get_monitor_analysis_result(result_id: str) -> MonitorAnalysisResult | None:
    with monitor_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_analysis_results WHERE id = ?",
            (result_id,),
        ).fetchone()
    return _row_to_monitor_analysis_result(row)


def list_monitor_analysis_results(limit: int = 100, offset: int = 0) -> list[MonitorAnalysisResult]:
    with monitor_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM monitor_analysis_results
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    return [_row_to_monitor_analysis_result(row) for row in rows if row is not None]


def _row_to_monitor_scan_window(row: sqlite3.Row | None) -> MonitorScanWindow | None:
    if row is None:
        return None
    return MonitorScanWindow(
        id=row["id"],
        window_start=datetime.fromisoformat(row["window_start"]),
        window_end=datetime.fromisoformat(row["window_end"]),
        trigger_type=MonitorScanTriggerType(row["trigger_type"]),
        status=MonitorScanWindowStatus(row["status"]),
        platforms=json.loads(row["platforms_json"]) if row["platforms_json"] else [],
        fetched_count=row["fetched_count"],
        deduplicated_count=row["deduplicated_count"],
        analyzed_count=row["analyzed_count"],
        duplicate_count=row["duplicate_count"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_monitor_window_item(row: sqlite3.Row | None) -> MonitorWindowItem | None:
    if row is None:
        return None
    return MonitorWindowItem(
        id=row["id"],
        window_id=row["window_id"],
        platform=row["platform"],
        platform_display_name=None,
        hot_item_id=row["hot_item_id"],
        analysis_result_id=row["analysis_result_id"],
        duplicate_of_analysis_result_id=row["duplicate_of_analysis_result_id"],
        analysis_status=row["analysis_status"] or "pending",
        dedupe_key=row["dedupe_key"],
        title=row["title"],
        url=row["url"],
        hot_value=row["hot_value"],
        rank=row["rank"],
        trend=row["trend"],
        is_duplicate_across_windows=bool(row["is_duplicate_across_windows"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


def create_monitor_scan_window(window: MonitorScanWindow) -> MonitorScanWindow:
    now = _utc_now().isoformat()
    created_at = window.created_at.isoformat() if window.created_at else now
    updated_at = window.updated_at.isoformat() if window.updated_at else now
    with monitor_connection() as conn:
        conn.execute(
            """
            INSERT INTO monitor_scan_windows (
                id, window_start, window_end, trigger_type, status, platforms_json,
                fetched_count, deduplicated_count, analyzed_count, duplicate_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                window_start = excluded.window_start,
                window_end = excluded.window_end,
                trigger_type = excluded.trigger_type,
                status = excluded.status,
                platforms_json = excluded.platforms_json,
                fetched_count = excluded.fetched_count,
                deduplicated_count = excluded.deduplicated_count,
                analyzed_count = excluded.analyzed_count,
                duplicate_count = excluded.duplicate_count,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                window.id,
                window.window_start.isoformat(),
                window.window_end.isoformat(),
                window.trigger_type.value,
                window.status.value,
                json.dumps(window.platforms, ensure_ascii=False),
                window.fetched_count,
                window.deduplicated_count,
                window.analyzed_count,
                window.duplicate_count,
                created_at,
                updated_at,
            ),
        )
        conn.commit()
    return window.model_copy(
        update={
            "created_at": datetime.fromisoformat(created_at),
            "updated_at": datetime.fromisoformat(updated_at),
        }
    )


def get_monitor_scan_window(window_id: str) -> MonitorScanWindow | None:
    with monitor_connection() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_scan_windows WHERE id = ?",
            (window_id,),
        ).fetchone()
    return _row_to_monitor_scan_window(row)


def list_monitor_scan_windows(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 24,
) -> list[MonitorScanWindow]:
    sql = "SELECT * FROM monitor_scan_windows WHERE 1=1"
    params: list[object] = []
    if start is not None:
        sql += " AND window_end >= ?"
        params.append(start.isoformat())
    if end is not None:
        sql += " AND window_end <= ?"
        params.append(end.isoformat())
    sql += " ORDER BY window_end DESC LIMIT ?"
    params.append(limit)
    with monitor_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_monitor_scan_window(row) for row in rows if row is not None]


def get_latest_monitor_scan_window() -> MonitorScanWindow | None:
    windows = list_monitor_scan_windows(limit=1)
    return windows[0] if windows else None


def save_monitor_window_item(item: MonitorWindowItem) -> MonitorWindowItem:
    created_at = item.created_at.isoformat()
    with monitor_connection() as conn:
        conn.execute(
            """
            INSERT INTO monitor_window_items (
                id, window_id, platform, hot_item_id, analysis_result_id, duplicate_of_analysis_result_id,
                analysis_status, dedupe_key, title, url, hot_value, rank, trend, is_duplicate_across_windows, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(window_id, dedupe_key) DO UPDATE SET
                platform = excluded.platform,
                hot_item_id = excluded.hot_item_id,
                analysis_result_id = excluded.analysis_result_id,
                duplicate_of_analysis_result_id = excluded.duplicate_of_analysis_result_id,
                analysis_status = excluded.analysis_status,
                title = excluded.title,
                url = excluded.url,
                hot_value = excluded.hot_value,
                rank = excluded.rank,
                trend = excluded.trend,
                is_duplicate_across_windows = excluded.is_duplicate_across_windows,
                created_at = excluded.created_at
            """,
            (
                item.id,
                item.window_id,
                item.platform,
                item.hot_item_id,
                item.analysis_result_id,
                item.duplicate_of_analysis_result_id,
                item.analysis_status,
                item.dedupe_key,
                item.title,
                item.url,
                item.hot_value,
                item.rank,
                item.trend.value,
                int(item.is_duplicate_across_windows),
                created_at,
            ),
        )
        conn.commit()
    return item


def list_monitor_window_items(window_id: str) -> list[MonitorWindowItem]:
    with monitor_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM monitor_window_items
            WHERE window_id = ?
            ORDER BY rank ASC, created_at DESC
            """,
            (window_id,),
        ).fetchall()
    return [_row_to_monitor_window_item(row) for row in rows if row is not None]


def get_monitor_window_item(item_id: str) -> MonitorWindowItem | None:
    with monitor_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM monitor_window_items
            WHERE id = ?
            LIMIT 1
            """,
            (item_id,),
        ).fetchone()
    return _row_to_monitor_window_item(row)


def update_monitor_window_item_analysis_result(
    *,
    window_id: str,
    dedupe_key: str,
    analysis_result_id: str,
    analysis_status: str = "done",
    is_duplicate_across_windows: bool = False,
    duplicate_of_analysis_result_id: str | None = None,
) -> int:
    with monitor_connection() as conn:
        result = conn.execute(
            """
            UPDATE monitor_window_items
            SET analysis_result_id = ?,
                analysis_status = ?,
                is_duplicate_across_windows = ?,
                duplicate_of_analysis_result_id = COALESCE(?, duplicate_of_analysis_result_id)
            WHERE window_id = ? AND dedupe_key = ?
            """,
            (
                analysis_result_id,
                analysis_status,
                int(is_duplicate_across_windows),
                duplicate_of_analysis_result_id,
                window_id,
                dedupe_key,
            ),
        )
        conn.commit()
    return result.rowcount


def update_monitor_window_item_analysis_status(
    *,
    window_id: str,
    dedupe_key: str,
    analysis_status: str,
) -> int:
    with monitor_connection() as conn:
        result = conn.execute(
            """
            UPDATE monitor_window_items
            SET analysis_status = ?
            WHERE window_id = ? AND dedupe_key = ?
            """,
            (
                analysis_status,
                window_id,
                dedupe_key,
            ),
        )
        conn.commit()
    return result.rowcount


def find_monitor_analysis_result_by_dedupe_key(dedupe_key: str) -> MonitorAnalysisResult | None:
    with monitor_connection() as conn:
        row = conn.execute(
            """
            SELECT * FROM monitor_analysis_results
            WHERE dedupe_key = ?
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 1
            """,
            (dedupe_key,),
        ).fetchone()
    return _row_to_monitor_analysis_result(row)


def update_monitor_scan_window_counters(
    window_id: str,
    *,
    analyzed_increment: int = 0,
    duplicate_increment: int = 0,
) -> MonitorScanWindow | None:
    window = get_monitor_scan_window(window_id)
    if window is None:
        return None
    return create_monitor_scan_window(
        window.model_copy(
            update={
                "analyzed_count": window.analyzed_count + analyzed_increment,
                "duplicate_count": window.duplicate_count + duplicate_increment,
                "updated_at": _utc_now(),
            }
        )
    )


def list_monitor_scan_window_details(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 24,
) -> list[MonitorScanWindowDetail]:
    windows = list_monitor_scan_windows(start=start, end=end, limit=limit)
    display_name_map = _platform_display_name_map()
    analysis_cache: dict[str, MonitorAnalysisResult | None] = {}
    details: list[MonitorScanWindowDetail] = []
    for window in windows:
        item_views: list[MonitorWindowItemView] = []
        for item in list_monitor_window_items(window.id):
            analysis_result = None
            if item.analysis_result_id:
                if item.analysis_result_id not in analysis_cache:
                    analysis_cache[item.analysis_result_id] = get_monitor_analysis_result(item.analysis_result_id)
                analysis_result = analysis_cache[item.analysis_result_id]
            item_views.append(
                MonitorWindowItemView(
                    **item.model_copy(
                        update={
                            "platform_display_name": display_name_map.get(item.platform, item.platform),
                        }
                    ).model_dump(),
                    analysis_result=analysis_result,
                )
            )
        details.append(MonitorScanWindowDetail(window=window, items=item_views))
    return details


def get_monitor_scan_window_detail(window_id: str) -> MonitorScanWindowDetail | None:
    window = get_monitor_scan_window(window_id)
    if window is None:
        return None
    display_name_map = _platform_display_name_map()
    item_views: list[MonitorWindowItemView] = []
    for item in list_monitor_window_items(window.id):
        analysis_result = (
            get_monitor_analysis_result(item.analysis_result_id)
            if item.analysis_result_id
            else None
        )
        item_views.append(
            MonitorWindowItemView(
                **item.model_copy(
                    update={
                        "platform_display_name": display_name_map.get(item.platform, item.platform),
                    }
                ).model_dump(),
                analysis_result=analysis_result,
            )
        )
    return MonitorScanWindowDetail(window=window, items=item_views)


def get_latest_monitor_scan_window_detail() -> MonitorScanWindowDetail | None:
    latest = get_latest_monitor_scan_window()
    if latest is None:
        return None
    return get_monitor_scan_window_detail(latest.id)
