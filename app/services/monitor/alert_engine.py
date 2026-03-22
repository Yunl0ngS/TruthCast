from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable

from app.schemas.monitor import Alert, AlertStatus, NotifyChannel, TriggerMode
from app.services.monitor.store import monitor_connection
from app.services.risk_snapshot import detect_risk_snapshot


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


def _row_to_alert(row) -> Alert:
    return Alert(
        id=row["id"],
        hot_item_id=row["hot_item_id"],
        trigger_reason=row["trigger_reason"],
        trigger_mode=row["trigger_mode"],
        matched_subscriptions=_load_json(row["matched_subscriptions_json"], []),
        matched_keywords=_load_json(row["matched_keywords_json"], []),
        risk_score=row["risk_score"],
        risk_level=row["risk_level"],
        risk_summary=row["risk_summary"],
        hot_item_title=row["hot_item_title"],
        hot_item_url=row["hot_item_url"],
        hot_item_platform=row["hot_item_platform"],
        hot_item_hot_value=row["hot_item_hot_value"],
        hot_item_rank=row["hot_item_rank"],
        status=row["status"],
        priority=row["priority"],
        notify_channels=_load_json(row["notify_channels_json"], []),
        notify_results=_load_json(row["notify_results_json"], []),
        created_at=datetime.fromisoformat(row["created_at"]),
        sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
        acknowledged_at=datetime.fromisoformat(row["acknowledged_at"])
        if row["acknowledged_at"]
        else None,
        acknowledged_by=row["acknowledged_by"],
        cooldown_until=datetime.fromisoformat(row["cooldown_until"])
        if row["cooldown_until"]
        else None,
    )


class AlertEngine:
    def __init__(
        self,
        subscription_service,
        hot_items_service,
        notifier,
        risk_evaluator: Callable[[str], Awaitable] | None = None,
        cooldown_minutes: int = 30,
    ):
        self.subscriptions = subscription_service
        self.hot_items = hot_items_service
        self.notifier = notifier
        self.cooldown_minutes = cooldown_minutes
        self.risk_evaluator = risk_evaluator or self._default_risk_evaluator
        self.recent_alerts: dict[str, datetime] = {}

    async def _default_risk_evaluator(self, text: str):
        return detect_risk_snapshot(text)

    async def check_and_alert(self, items: list, platform: str) -> list[Alert]:  # noqa: ANN001
        alerts: list[Alert] = []
        for item in items:
            if not await self._should_check(item):
                continue

            matched_subs = await self.subscriptions.match(item.title, [platform])
            if not matched_subs:
                continue

            if item.risk_score is None:
                risk_result = await self.risk_evaluator(item.title)
                item.risk_score = risk_result.score
                item.risk_level = risk_result.label
                await self.hot_items.update_risk(item.id, item.risk_score, item.risk_level)

            should_alert, trigger_info = await self._evaluate_trigger(item, matched_subs)
            if not should_alert:
                continue

            alert = await self._create_and_send_alert(item, trigger_info["subscriptions"], trigger_info)
            alerts.append(alert)
            self.recent_alerts[item.id] = _utc_now()
        return alerts

    async def _should_check(self, item) -> bool:  # noqa: ANN001
        last_alert = self.recent_alerts.get(item.id)
        if last_alert is None:
            return True
        return (_utc_now() - last_alert).total_seconds() >= self.cooldown_minutes * 60

    async def _evaluate_trigger(self, item, matched_subs: list) -> tuple[bool, dict]:  # noqa: ANN001
        triggered_subs = []
        reasons = []
        for sub in matched_subs:
            if sub.trigger_mode == TriggerMode.HIT:
                triggered_subs.append(sub)
                reasons.append(f"订阅 [{sub.name}] 命中即触发")
            elif sub.trigger_mode == TriggerMode.THRESHOLD:
                if (item.risk_score or 0) >= sub.risk_threshold:
                    triggered_subs.append(sub)
                    reasons.append(
                        f"订阅 [{sub.name}] 风险分数 {item.risk_score} >= {sub.risk_threshold}"
                    )
            elif sub.trigger_mode == TriggerMode.SMART:
                smart_score = await self._calculate_smart_score(item)
                if smart_score >= 0.7:
                    triggered_subs.append(sub)
                    reasons.append(f"订阅 [{sub.name}] 智能评分 {smart_score:.2f}")
        return bool(triggered_subs), {"subscriptions": triggered_subs, "reasons": reasons}

    async def _calculate_smart_score(self, item) -> float:  # noqa: ANN001
        risk_score = min(max((item.risk_score or 0) / 100.0, 0.0), 1.0)
        hot_score = min(max(item.hot_value / 1000.0, 0.0), 1.0)
        trend_score = 1.0 if getattr(item, "trend", None) in {"new", "rising"} else 0.5
        return min((risk_score * 0.5) + (hot_score * 0.3) + (trend_score * 0.2), 1.0)

    async def _create_and_send_alert(self, item, subs: list, trigger_info: dict) -> Alert:  # noqa: ANN001
        notify_channels = list(
            {
                channel.value if hasattr(channel, "value") else str(channel)
                for sub in subs
                for channel in sub.notify_channels
            }
        )
        alert = Alert(
            id=f"alert_{uuid.uuid4().hex[:12]}",
            hot_item_id=item.id,
            trigger_reason="; ".join(trigger_info.get("reasons", [])),
            trigger_mode=subs[0].trigger_mode if subs else TriggerMode.THRESHOLD,
            matched_subscriptions=[sub.id for sub in subs],
            matched_keywords=sorted(
                {
                    keyword
                    for sub in subs
                    for keyword in sub.keywords
                    if keyword and keyword.lower() in item.title.lower()
                }
            ),
            risk_score=item.risk_score or 0,
            risk_level=item.risk_level or "needs_context",
            hot_item_title=item.title,
            hot_item_url=item.url,
            hot_item_platform=item.platform,
            hot_item_hot_value=item.hot_value,
            hot_item_rank=item.rank,
            status=AlertStatus.PENDING,
            priority=max((sub.priority for sub in subs), default=0),
            notify_channels=[NotifyChannel(channel) for channel in notify_channels],
            cooldown_until=_utc_now() + timedelta(minutes=self.cooldown_minutes),
        )
        alert.notify_results = await self.notifier.send(alert, subs)
        alert.status = AlertStatus.SENT
        alert.sent_at = _utc_now()
        await self.save_alert(alert)
        return alert

    async def save_alert(self, alert: Alert) -> None:
        with monitor_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO monitor_alerts (
                    id, hot_item_id, trigger_reason, trigger_mode, matched_subscriptions_json,
                    matched_keywords_json, risk_score, risk_level, risk_summary, hot_item_title,
                    hot_item_url, hot_item_platform, hot_item_hot_value, hot_item_rank, status,
                    priority, notify_channels_json, notify_results_json, created_at, sent_at,
                    acknowledged_at, acknowledged_by, cooldown_until
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert.id,
                    alert.hot_item_id,
                    alert.trigger_reason,
                    alert.trigger_mode.value,
                    _dump_json(alert.matched_subscriptions),
                    _dump_json(alert.matched_keywords),
                    alert.risk_score,
                    alert.risk_level,
                    alert.risk_summary,
                    alert.hot_item_title,
                    alert.hot_item_url,
                    alert.hot_item_platform,
                    alert.hot_item_hot_value,
                    alert.hot_item_rank,
                    alert.status.value,
                    alert.priority,
                    _dump_json([channel.value for channel in alert.notify_channels]),
                    _dump_json(alert.notify_results),
                    alert.created_at.isoformat(),
                    alert.sent_at.isoformat() if alert.sent_at else None,
                    alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
                    alert.acknowledged_by,
                    alert.cooldown_until.isoformat() if alert.cooldown_until else None,
                ),
            )
            conn.commit()

    async def list_alerts(self, limit: int = 100, offset: int = 0) -> list[Alert]:
        with monitor_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM monitor_alerts
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return [_row_to_alert(row) for row in rows]

    async def get_alert(self, alert_id: str) -> Alert | None:
        with monitor_connection() as conn:
            row = conn.execute(
                "SELECT * FROM monitor_alerts WHERE id = ?",
                (alert_id,),
            ).fetchone()
        return _row_to_alert(row) if row else None

    async def acknowledge(self, alert_id: str, acknowledged_by: str = "system") -> bool:
        with monitor_connection() as conn:
            result = conn.execute(
                """
                UPDATE monitor_alerts
                SET status = ?, acknowledged_at = ?, acknowledged_by = ?
                WHERE id = ?
                """,
                (
                    AlertStatus.ACKNOWLEDGED.value,
                    _utc_now().isoformat(),
                    acknowledged_by,
                    alert_id,
                ),
            )
            conn.commit()
        return result.rowcount > 0
