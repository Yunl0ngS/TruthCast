from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.schemas.monitor import Alert, NotifyChannel, Subscription, SubscriptionType, TriggerMode
from app.services.monitor.notifier import EmailChannel, NotifierService, WebhookChannel


def _sample_alert(channel: NotifyChannel = NotifyChannel.WEBHOOK) -> Alert:
    return Alert(
        id="alert_1",
        hot_item_id="hot_1",
        trigger_reason="订阅命中",
        trigger_mode=TriggerMode.HIT,
        risk_score=86,
        risk_level="high_risk",
        hot_item_title="某地突发事件登上热搜",
        hot_item_url="https://example.com/hot/1",
        hot_item_platform="weibo",
        hot_item_hot_value=500,
        hot_item_rank=1,
        notify_channels=[channel],
        created_at=datetime.now(timezone.utc),
    )


def _sample_subscription(name: str, notify_channel: NotifyChannel, notify_config: dict) -> Subscription:
    return Subscription(
        id=f"sub_{name}",
        user_id="demo-user",
        name=name,
        type=SubscriptionType.KEYWORD,
        keywords=["突发事件"],
        trigger_mode=TriggerMode.HIT,
        notify_channels=[notify_channel],
        notify_config=notify_config,
    )


def test_notifier_service_merges_channel_config_and_dispatches(monkeypatch) -> None:
    notifier = NotifierService()
    captured: dict[str, object] = {}

    class _FakeWebhookChannel:
        async def send(self, alert, config):
            captured["alert_id"] = alert.id
            captured["config"] = config
            return {"success": True, "message": "ok", "response": {"received": True}}

    notifier.channels[NotifyChannel.WEBHOOK] = _FakeWebhookChannel()

    subscriptions = [
        _sample_subscription(
            "a",
            NotifyChannel.WEBHOOK,
            {"webhook": {"url": "https://example.com/hook", "headers": {"X-A": "1"}}},
        ),
        _sample_subscription(
            "b",
            NotifyChannel.WEBHOOK,
            {"webhook": {"method": "PUT", "headers": {"X-B": "2"}}},
        ),
    ]

    results = asyncio.run(notifier.send(_sample_alert(), subscriptions))

    assert results[0]["success"] is True
    assert captured["alert_id"] == "alert_1"
    assert captured["config"] == {
        "url": "https://example.com/hook",
        "method": "PUT",
        "headers": {"X-A": "1", "X-B": "2"},
    }


def test_webhook_channel_posts_json_payload(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeResponse:
        status_code = 200

        def json(self):
            return {"ok": True}

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, method, url, json=None, headers=None):
            captured["method"] = method
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr("app.services.monitor.notifier.httpx.AsyncClient", lambda timeout=10.0: _FakeClient())

    result = asyncio.run(
        WebhookChannel().send(
            _sample_alert(),
            {"url": "https://example.com/hook", "method": "POST", "headers": {"X-Test": "1"}},
        )
    )

    assert result["success"] is True
    assert captured["method"] == "POST"
    assert captured["url"] == "https://example.com/hook"
    assert captured["headers"] == {"X-Test": "1"}
    assert captured["json"]["id"] == "alert_1"


def test_email_channel_sends_message(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeSMTP:
        def __init__(self, host, port):
            captured["host"] = host
            captured["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def starttls(self):
            captured["tls"] = True

        def login(self, user, password):
            captured["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, message):
            captured["sendmail"] = (from_addr, to_addrs, message)

    monkeypatch.setattr("app.services.monitor.notifier.smtplib.SMTP", _FakeSMTP)

    result = asyncio.run(
        EmailChannel().send(
            _sample_alert(NotifyChannel.EMAIL),
            {
                "smtp_host": "smtp.example.com",
                "smtp_port": 587,
                "smtp_user": "bot@example.com",
                "smtp_password": "secret",
                "from_addr": "bot@example.com",
                "to_addrs": ["ops@example.com"],
            },
        )
    )

    assert result["success"] is True
    assert captured["host"] == "smtp.example.com"
    assert captured["tls"] is True
    assert captured["login"] == ("bot@example.com", "secret")
    assert captured["sendmail"][0] == "bot@example.com"
