from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from app.schemas.monitor import Subscription, SubscriptionCreate
from app.services.monitor.store import monitor_connection


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


def _row_to_subscription(row) -> Subscription:
    return Subscription(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        type=row["type"],
        keywords=_load_json(row["keywords_json"], []),
        match_mode=row["match_mode"],
        platforms=_load_json(row["platforms_json"], []),
        exclude_keywords=_load_json(row["exclude_keywords_json"], []),
        trigger_mode=row["trigger_mode"],
        risk_threshold=row["risk_threshold"],
        smart_threshold=_load_json(row["smart_threshold_json"], {}),
        notify_channels=_load_json(row["notify_channels_json"], []),
        notify_config=_load_json(row["notify_config_json"], {}),
        notify_template=row["notify_template"],
        quiet_hours=_load_json(row["quiet_hours_json"], None),
        is_active=bool(row["is_active"]),
        priority=row["priority"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SubscriptionService:
    async def create(self, sub: SubscriptionCreate, user_id: str) -> Subscription:
        subscription = Subscription(
            id=f"sub_{uuid.uuid4().hex[:12]}",
            user_id=user_id,
            **sub.model_dump(),
        )
        with monitor_connection() as conn:
            conn.execute(
                """
                INSERT INTO monitor_subscriptions (
                    id, user_id, name, type, keywords_json, match_mode, platforms_json,
                    exclude_keywords_json, trigger_mode, risk_threshold, smart_threshold_json,
                    notify_channels_json, notify_config_json, notify_template, quiet_hours_json,
                    is_active, priority, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription.id,
                    subscription.user_id,
                    subscription.name,
                    subscription.type.value,
                    _dump_json(subscription.keywords),
                    subscription.match_mode,
                    _dump_json(subscription.platforms),
                    _dump_json(subscription.exclude_keywords),
                    subscription.trigger_mode.value,
                    subscription.risk_threshold,
                    _dump_json(subscription.smart_threshold),
                    _dump_json([channel.value for channel in subscription.notify_channels]),
                    _dump_json(subscription.notify_config),
                    subscription.notify_template,
                    _dump_json(subscription.quiet_hours) if subscription.quiet_hours else None,
                    int(subscription.is_active),
                    subscription.priority,
                    subscription.created_at.isoformat(),
                    subscription.updated_at.isoformat(),
                ),
            )
            conn.commit()
        return subscription

    async def list(
        self, user_id: str, is_active: bool | None = None
    ) -> list[Subscription]:
        sql = """
            SELECT * FROM monitor_subscriptions
            WHERE user_id = ?
        """
        params: list[object] = [user_id]
        if is_active is not None:
            sql += " AND is_active = ?"
            params.append(int(is_active))
        sql += " ORDER BY priority DESC, created_at DESC"

        with monitor_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_subscription(row) for row in rows]

    async def get(self, sub_id: str) -> Subscription | None:
        with monitor_connection() as conn:
            row = conn.execute(
                "SELECT * FROM monitor_subscriptions WHERE id = ?", (sub_id,)
            ).fetchone()
        return _row_to_subscription(row) if row else None

    async def update(self, sub_id: str, updates: dict) -> Subscription | None:
        current = await self.get(sub_id)
        if current is None:
            return None

        payload = current.model_dump()
        payload.update({key: value for key, value in updates.items() if value is not None})
        payload["updated_at"] = _utc_now()
        updated = Subscription(**payload)

        with monitor_connection() as conn:
            conn.execute(
                """
                UPDATE monitor_subscriptions
                SET name = ?, keywords_json = ?, match_mode = ?, platforms_json = ?,
                    exclude_keywords_json = ?, trigger_mode = ?, risk_threshold = ?,
                    smart_threshold_json = ?, notify_channels_json = ?, notify_config_json = ?,
                    notify_template = ?, quiet_hours_json = ?, is_active = ?, priority = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    updated.name,
                    _dump_json(updated.keywords),
                    updated.match_mode,
                    _dump_json(updated.platforms),
                    _dump_json(updated.exclude_keywords),
                    updated.trigger_mode.value,
                    updated.risk_threshold,
                    _dump_json(updated.smart_threshold),
                    _dump_json([channel.value for channel in updated.notify_channels]),
                    _dump_json(updated.notify_config),
                    updated.notify_template,
                    _dump_json(updated.quiet_hours) if updated.quiet_hours else None,
                    int(updated.is_active),
                    updated.priority,
                    updated.updated_at.isoformat(),
                    sub_id,
                ),
            )
            conn.commit()
        return updated

    async def delete(self, sub_id: str) -> bool:
        with monitor_connection() as conn:
            result = conn.execute(
                "DELETE FROM monitor_subscriptions WHERE id = ?", (sub_id,)
            )
            conn.commit()
        return result.rowcount > 0

    async def match(self, title: str, platforms: list[str]) -> list[Subscription]:
        with monitor_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM monitor_subscriptions WHERE is_active = 1"
            ).fetchall()

        title_text = title.lower()
        platform_set = {item.lower() for item in platforms}
        matches: list[Subscription] = []

        for row in rows:
            subscription = _row_to_subscription(row)
            if subscription.platforms:
                sub_platforms = {item.lower() for item in subscription.platforms}
                if not sub_platforms.intersection(platform_set):
                    continue

            exclude_keywords = [item.lower() for item in subscription.exclude_keywords]
            if any(keyword and keyword in title_text for keyword in exclude_keywords):
                continue

            keywords = [item.lower() for item in subscription.keywords if item.strip()]
            if not keywords:
                continue

            if subscription.match_mode == "all":
                matched = all(keyword in title_text for keyword in keywords)
            elif subscription.match_mode == "regex":
                matched = any(re.search(keyword, title, flags=re.IGNORECASE) for keyword in keywords)
            else:
                matched = any(keyword in title_text for keyword in keywords)

            if matched:
                matches.append(subscription)

        matches.sort(key=lambda item: (-item.priority, item.created_at))
        return matches

