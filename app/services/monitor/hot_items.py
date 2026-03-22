from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

import httpx

from app.schemas.monitor import HotItem, TrendDirection
from app.services.monitor.platform_config import load_enabled_monitor_platforms
from app.services.monitor.store import monitor_connection

logger = logging.getLogger(__name__)

DEFAULT_NEWSNOW_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/91.0.4472.124 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
}

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dump_json(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: str | None, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _base_url() -> str:
    return os.getenv("TRUTHCAST_NEWSNOW_BASE_URL", "https://newsnow.busiyi.world/api/s").rstrip("/")


def _row_to_hot_item(row) -> HotItem:
    return HotItem(
        id=row["id"],
        platform=row["platform"],
        title=row["title"],
        url=row["url"],
        summary=row["summary"],
        cover_image=row["cover_image"],
        hot_value=row["hot_value"],
        rank=row["rank"],
        trend=row["trend"],
        risk_score=row["risk_score"],
        risk_level=row["risk_level"],
        risk_assessed_at=datetime.fromisoformat(row["risk_assessed_at"])
        if row["risk_assessed_at"]
        else None,
        first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
        last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
        last_hot_value=row["last_hot_value"],
        extra=_load_json(row["extra_json"], {}),
        raw_data=_load_json(row["raw_data_json"], {}),
    )


class HotItemsService:
    def __init__(self, newsnow_base_url: str | None = None):
        self.newsnow_base_url = newsnow_base_url or _base_url()
        self.platform_configs = load_enabled_monitor_platforms()
        self.platform_ids = {item.key: item.newsnow_id for item in self.platform_configs}
        self.platform_intervals = {
            item.key: item.scan_interval_minutes
            for item in self.platform_configs
        }
        self.platform_fetch_limits = {item.key: item.fetch_top_n for item in self.platform_configs}

    async def get_platforms(self) -> list[str]:
        return list(self.platform_ids.keys())

    async def fetch_platform(self, platform: str) -> list[HotItem]:
        platform_key = platform.lower()
        platform_id = self.platform_ids.get(platform_key, platform_key)
        body = await self._request_json(platform_id)
        items = body.get("items", []) if isinstance(body, dict) else []
        if not isinstance(items, list):
            return []
        normalized = [
            self._normalize_item(platform_key, item, rank=index)
            for index, item in enumerate(items, start=1)
            if isinstance(item, dict)
        ]
        limit = self.platform_fetch_limits.get(platform_key)
        if limit is not None and limit > 0:
            return normalized[:limit]
        return normalized

    async def fetch_all(self) -> dict[str, list[HotItem]]:
        result: dict[str, list[HotItem]] = {}
        for platform in await self.get_platforms():
            try:
                items = await self.fetch_platform(platform)
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("拉取 NewsNow 平台失败: %s (%s)", platform, exc)
                continue
            result[platform] = items
        return result

    async def detect_incremental(
        self, new_items: list[HotItem], platform: str
    ) -> dict[str, list[HotItem]]:
        existing = {item.id: item for item in await self.list(platform=platform, limit=1000)}
        current_ids = {item.id for item in new_items}

        new: list[HotItem] = []
        updated: list[HotItem] = []
        removed: list[HotItem] = []

        for item in new_items:
            previous = existing.get(item.id)
            if previous is None:
                item.trend = TrendDirection.NEW
                new.append(item)
                continue

            item.first_seen_at = previous.first_seen_at
            item.last_seen_at = _utc_now()
            item.last_hot_value = previous.hot_value
            if item.hot_value > previous.hot_value:
                item.trend = TrendDirection.RISING
            elif item.hot_value < previous.hot_value:
                item.trend = TrendDirection.FALLING
            else:
                item.trend = TrendDirection.STABLE

            if (
                item.hot_value != previous.hot_value
                or item.rank != previous.rank
                or item.title != previous.title
            ):
                updated.append(item)

        for item_id, item in existing.items():
            if item_id not in current_ids:
                removed.append(item)

        return {"new": new, "updated": updated, "removed": removed}

    async def save(self, items: list[HotItem]) -> int:
        if not items:
            return 0

        now = _utc_now()
        with monitor_connection() as conn:
            for item in items:
                existing = conn.execute(
                    "SELECT first_seen_at, hot_value FROM monitor_hot_items WHERE id = ?",
                    (item.id,),
                ).fetchone()
                first_seen_at = (
                    existing["first_seen_at"] if existing else item.first_seen_at.isoformat()
                )
                last_hot_value = existing["hot_value"] if existing else item.last_hot_value
                conn.execute(
                    """
                    INSERT INTO monitor_hot_items (
                        id, platform, title, url, summary, cover_image, hot_value, rank, trend,
                        risk_score, risk_level, risk_assessed_at, first_seen_at, last_seen_at,
                        last_hot_value, extra_json, raw_data_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        platform = excluded.platform,
                        title = excluded.title,
                        url = excluded.url,
                        summary = excluded.summary,
                        cover_image = excluded.cover_image,
                        hot_value = excluded.hot_value,
                        rank = excluded.rank,
                        trend = excluded.trend,
                        risk_score = COALESCE(excluded.risk_score, monitor_hot_items.risk_score),
                        risk_level = COALESCE(excluded.risk_level, monitor_hot_items.risk_level),
                        risk_assessed_at = COALESCE(excluded.risk_assessed_at, monitor_hot_items.risk_assessed_at),
                        first_seen_at = excluded.first_seen_at,
                        last_seen_at = excluded.last_seen_at,
                        last_hot_value = excluded.last_hot_value,
                        extra_json = excluded.extra_json,
                        raw_data_json = excluded.raw_data_json
                    """,
                    (
                        item.id,
                        item.platform,
                        item.title,
                        item.url,
                        item.summary,
                        item.cover_image,
                        item.hot_value,
                        item.rank,
                        item.trend.value,
                        item.risk_score,
                        item.risk_level,
                        item.risk_assessed_at.isoformat() if item.risk_assessed_at else None,
                        first_seen_at,
                        now.isoformat(),
                        last_hot_value,
                        _dump_json(item.extra),
                        _dump_json(item.raw_data),
                    ),
                )
            conn.commit()
        return len(items)

    async def list(
        self,
        platform: str | None = None,
        risk_level: str | None = None,
        min_risk_score: int | None = None,
        trend: TrendDirection | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[HotItem]:
        sql = "SELECT * FROM monitor_hot_items WHERE 1=1"
        params: list[object] = []
        if platform:
            sql += " AND platform = ?"
            params.append(platform)
        if risk_level:
            sql += " AND risk_level = ?"
            params.append(risk_level)
        if min_risk_score is not None:
            sql += " AND risk_score >= ?"
            params.append(min_risk_score)
        if trend is not None:
            sql += " AND trend = ?"
            params.append(trend.value)
        sql += " ORDER BY last_seen_at DESC, rank ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with monitor_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_hot_item(row) for row in rows]

    async def get(self, item_id: str) -> HotItem | None:
        with monitor_connection() as conn:
            row = conn.execute(
                "SELECT * FROM monitor_hot_items WHERE id = ?", (item_id,)
            ).fetchone()
        return _row_to_hot_item(row) if row else None

    async def update_risk(self, item_id: str, risk_score: int, risk_level: str) -> bool:
        with monitor_connection() as conn:
            result = conn.execute(
                """
                UPDATE monitor_hot_items
                SET risk_score = ?, risk_level = ?, risk_assessed_at = ?
                WHERE id = ?
                """,
                (risk_score, risk_level, _utc_now().isoformat(), item_id),
            )
            conn.commit()
        return result.rowcount > 0

    async def _request_json(self, platform_id: str):
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                self.newsnow_base_url,
                params={"id": platform_id, "latest": ""},
                headers=DEFAULT_NEWSNOW_HEADERS,
            )
            response.raise_for_status()
            payload = response.json()
            status = payload.get("status", "unknown") if isinstance(payload, dict) else "unknown"
            if status not in {"success", "cache"}:
                raise ValueError(f"unexpected NewsNow status: {status}")
            return payload

    def _normalize_item(self, platform: str, item: dict, rank: int = 0) -> HotItem:
        title = str(item.get("title", "")).strip()
        url = str(item.get("url") or item.get("mobileUrl") or "").strip()
        item_id = str(item.get("id") or f"{platform}_{abs(hash((title, url))) % 10**10}")
        hot_value = int(item.get("hot_value") or item.get("hot") or item.get("hotValue") or 0)
        resolved_rank = int(item.get("rank") or rank or 0)
        return HotItem(
            id=item_id,
            platform=platform,
            title=title,
            url=url,
            summary=item.get("summary"),
            cover_image=item.get("cover_image"),
            hot_value=hot_value,
            rank=resolved_rank,
            trend=TrendDirection.NEW,
            last_hot_value=0,
            extra=item.get("extra", {}),
            raw_data=item,
        )
