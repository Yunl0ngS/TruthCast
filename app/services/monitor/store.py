from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
        conn.commit()


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

