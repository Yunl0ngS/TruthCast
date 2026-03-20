import asyncio

import httpx

from app.schemas.monitor import HotItem, TrendDirection
from app.services.monitor.hot_items import HotItemsService
from app.services.monitor.store import init_monitor_db


def test_detect_incremental_marks_new_updated_and_removed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_DB_PATH", str(tmp_path / "monitor.db"))
    init_monitor_db()
    service = HotItemsService()

    existing = HotItem(
        id="weibo_old",
        platform="weibo",
        title="旧热点",
        url="https://example.com/old",
        hot_value=100,
        last_hot_value=100,
        rank=5,
        trend=TrendDirection.STABLE,
    )
    asyncio.run(service.save([existing]))

    new_items = [
        HotItem(
            id="weibo_old",
            platform="weibo",
            title="旧热点",
            url="https://example.com/old",
            hot_value=180,
            last_hot_value=100,
            rank=2,
            trend=TrendDirection.NEW,
        ),
        HotItem(
            id="weibo_new",
            platform="weibo",
            title="新热点",
            url="https://example.com/new",
            hot_value=90,
            last_hot_value=0,
            rank=8,
            trend=TrendDirection.NEW,
        ),
    ]

    delta = asyncio.run(service.detect_incremental(new_items, "weibo"))

    assert [item.id for item in delta["new"]] == ["weibo_new"]
    assert [item.id for item in delta["updated"]] == ["weibo_old"]
    assert delta["updated"][0].trend == TrendDirection.RISING
    assert delta["removed"] == []


def test_fetch_platform_uses_newsnow_query_api_and_parses_items(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, headers=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return httpx.Response(
                200,
                request=httpx.Request("GET", url, params=params, headers=headers),
                json={
                    "status": "success",
                    "items": [
                        {
                            "title": "微博热搜测试",
                            "url": "https://example.com/weibo/1",
                            "mobileUrl": "https://m.example.com/weibo/1",
                            "hot": 321,
                        }
                    ],
                },
            )

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    service = HotItemsService("https://newsnow.busiyi.world/api/s")

    items = asyncio.run(service.fetch_platform("weibo"))

    assert len(items) == 1
    assert items[0].platform == "weibo"
    assert items[0].title == "微博热搜测试"
    assert items[0].url == "https://example.com/weibo/1"
    assert items[0].hot_value == 321
    assert captured["url"] == "https://newsnow.busiyi.world/api/s"
    assert captured["params"] == {"id": "weibo", "latest": ""}
    assert "Mozilla/5.0" in str(captured["headers"])


def test_fetch_platform_accepts_cache_status(monkeypatch) -> None:
    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, params=None, headers=None):
            return httpx.Response(
                200,
                request=httpx.Request("GET", url, params=params, headers=headers),
                json={"status": "cache", "items": [{"title": "知乎缓存热点", "url": "https://example.com/zhihu/1"}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    service = HotItemsService("https://newsnow.busiyi.world/api/s")

    items = asyncio.run(service.fetch_platform("zhihu"))

    assert len(items) == 1
    assert items[0].platform == "zhihu"
    assert items[0].title == "知乎缓存热点"


def test_fetch_all_continues_when_single_platform_fails(monkeypatch) -> None:
    service = HotItemsService("https://newsnow.busiyi.world/api/s")

    async def _fake_get_platforms():
        return ["weibo", "zhihu"]

    monkeypatch.setattr(service, "get_platforms", _fake_get_platforms)

    async def _fake_fetch_platform(platform: str):
        if platform == "zhihu":
            raise httpx.HTTPStatusError(
                "forbidden",
                request=httpx.Request("GET", "https://newsnow.busiyi.world/api/s"),
                response=httpx.Response(403),
            )
        return [
            HotItem(
                id="weibo_1",
                platform="weibo",
                title="微博热点",
                url="https://example.com/weibo/1",
                hot_value=100,
                rank=1,
                trend=TrendDirection.NEW,
            )
        ]

    monkeypatch.setattr(service, "fetch_platform", _fake_fetch_platform)

    grouped = asyncio.run(service.fetch_all())

    assert list(grouped.keys()) == ["weibo"]
    assert grouped["weibo"][0].id == "weibo_1"


def test_hot_items_service_uses_enabled_platform_config(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
platforms:
  - key: weibo
    display_name: 微博
    newsnow_id: weibo-hot
    enabled: true
    scan_interval_minutes: 5
  - key: zhihu
    display_name: 知乎
    newsnow_id: zhihu-hot
    enabled: false
    scan_interval_minutes: 10
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(config_path))

    service = HotItemsService("https://newsnow.busiyi.world/api/s")

    assert asyncio.run(service.get_platforms()) == ["weibo"]
    assert service.platform_ids == {"weibo": "weibo-hot"}
    assert service.platform_intervals == {"weibo": 5}
