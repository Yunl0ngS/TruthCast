import asyncio

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
from app.services.monitor.store import init_monitor_db
from app.services.monitor.subscription import SubscriptionService
from app.services.text_complexity import ScoreResult


class _FakeNotifier(NotifierService):
    async def send(self, alert, subscriptions):
        return [
            {
                "channel": "webhook",
                "success": True,
                "message": f"sent:{len(subscriptions)}",
            }
        ]


def test_alert_engine_triggers_threshold_and_respects_cooldown(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    init_monitor_db()

    subscription_service = SubscriptionService()
    hot_items_service = HotItemsService()
    notifier = _FakeNotifier()

    async def _fake_risk(_text: str) -> ScoreResult:
        return ScoreResult(
            label="high_risk",
            score=88,
            confidence=0.92,
            reasons=["命中高风险模式"],
            strategy=None,
        )

    engine = AlertEngine(
        subscription_service=subscription_service,
        hot_items_service=hot_items_service,
        notifier=notifier,
        risk_evaluator=_fake_risk,
        cooldown_minutes=30,
    )

    asyncio.run(
        subscription_service.create(
            SubscriptionCreate(
                name="事件监测",
                type=SubscriptionType.KEYWORD,
                keywords=["突发事件"],
                platforms=["weibo"],
                trigger_mode=TriggerMode.THRESHOLD,
                risk_threshold=70,
                notify_channels=[NotifyChannel.WEBHOOK],
                notify_config={"webhook": {"url": "https://example.com/hook"}},
            ),
            user_id="demo-user",
        )
    )

    hot_item = HotItem(
        id="weibo_hot_alert",
        platform="weibo",
        title="某地突发事件登上热搜",
        url="https://example.com/hot-alert",
        hot_value=300,
        rank=1,
        trend=TrendDirection.NEW,
    )
    asyncio.run(hot_items_service.save([hot_item]))

    first_alerts = asyncio.run(engine.check_and_alert([hot_item], "weibo"))
    assert len(first_alerts) == 1
    assert first_alerts[0].risk_score == 88
    assert first_alerts[0].status == "sent"

    second_alerts = asyncio.run(engine.check_and_alert([hot_item], "weibo"))
    assert second_alerts == []
