import asyncio
import sqlite3

from app.schemas.monitor import (
    NotifyChannel,
    SubscriptionCreate,
    SubscriptionType,
    TriggerMode,
)
from app.services.monitor.store import init_monitor_db
from app.services.monitor.subscription import SubscriptionService


def test_monitor_db_init_creates_tables(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "monitor.db"
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(db_path))

    init_monitor_db()

    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert "monitor_subscriptions" in tables
    assert "monitor_hot_items" in tables
    assert "monitor_alerts" in tables


def test_subscription_crud_and_match_filters_platform_and_keywords(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "monitor.db"
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(db_path))
    init_monitor_db()
    service = SubscriptionService()

    created = asyncio.run(
        service.create(
            SubscriptionCreate(
                name="流感监测",
                type=SubscriptionType.KEYWORD,
                keywords=["流感", "甲流"],
                platforms=["weibo"],
                exclude_keywords=["辟谣"],
                trigger_mode=TriggerMode.THRESHOLD,
                risk_threshold=60,
                notify_channels=[NotifyChannel.WEBHOOK],
                notify_config={"webhook": {"url": "https://example.com/hook"}},
            ),
            user_id="demo-user",
        )
    )

    listed = asyncio.run(service.list("demo-user"))
    assert [item.id for item in listed] == [created.id]

    matched = asyncio.run(service.match("流感相关消息冲上热搜", ["weibo"]))
    assert [item.id for item in matched] == [created.id]

    no_platform_match = asyncio.run(service.match("流感相关消息冲上热搜", ["zhihu"]))
    assert no_platform_match == []

    excluded = asyncio.run(service.match("官方已经辟谣该流感传闻", ["weibo"]))
    assert excluded == []

    updated = asyncio.run(
        service.update(
            created.id,
            {
                "name": "甲流重点监测",
                "risk_threshold": 80,
                "is_active": False,
            },
        )
    )
    assert updated is not None
    assert updated.name == "甲流重点监测"
    assert updated.risk_threshold == 80
    assert updated.is_active is False

    deleted = asyncio.run(service.delete(created.id))
    assert deleted is True
    assert asyncio.run(service.get(created.id)) is None

