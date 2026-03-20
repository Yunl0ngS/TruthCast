from pathlib import Path


def test_load_platform_configs_reads_yaml_and_filters_enabled(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
platforms:
  - key: weibo
    display_name: 微博
    newsnow_id: weibo
    enabled: true
    scan_interval_minutes: 5
  - key: zhihu
    display_name: 知乎
    newsnow_id: zhihu
    enabled: false
    scan_interval_minutes: 15
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(config_path))

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()

    assert [item.key for item in platforms] == ["weibo"]
    assert platforms[0].display_name == "微博"
    assert platforms[0].newsnow_id == "weibo"
    assert platforms[0].scan_interval_minutes == 5


def test_load_platform_configs_supports_env_overrides(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
platforms:
  - key: weibo
    display_name: 微博
    newsnow_id: weibo
    enabled: true
    scan_interval_minutes: 5
  - key: zhihu
    display_name: 知乎
    newsnow_id: zhihu
    enabled: true
    scan_interval_minutes: 12
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(config_path))
    monkeypatch.setenv("TRUTHCAST_MONITOR_ENABLED_PLATFORMS", "zhihu")
    monkeypatch.setenv('TRUTHCAST_NEWSNOW_PLATFORM_IDS', '{"zhihu":"zhihu-hot"}')

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()

    assert [item.key for item in platforms] == ["zhihu"]
    assert platforms[0].newsnow_id == "zhihu-hot"
    assert platforms[0].scan_interval_minutes == 12


def test_load_platform_configs_falls_back_to_default_when_file_missing(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(Path("/tmp/not-exists-monitor-platforms.yaml")))

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()

    keys = {item.key for item in platforms}
    assert "thepaper" in keys
    assert "wallstreetcn-hot" in keys
    assert "cls-telegraph" in keys
    assert "weibo" not in keys


def test_default_monitor_platform_config_prefers_news_media_over_social(tmp_path, monkeypatch) -> None:
    config_path = Path("/home/eryndor/code/TruthCast/config/monitor_platforms.yaml")
    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(config_path))
    monkeypatch.delenv("TRUTHCAST_MONITOR_ENABLED_PLATFORMS", raising=False)
    monkeypatch.delenv("TRUTHCAST_NEWSNOW_PLATFORM_IDS", raising=False)
    monkeypatch.delenv("TRUTHCAST_MONITOR_PLATFORM_INTERVALS", raising=False)

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()
    keys = {item.key for item in platforms}

    assert {
        "thepaper",
        "ifeng",
        "cankaoxiaoxi",
        "wallstreetcn-hot",
        "wallstreetcn-quick",
        "tencent-hot",
        "zaobao",
        "cls-hot",
        "cls-telegraph",
    }.issubset(keys)
    assert "weibo" not in keys
    assert "zhihu" not in keys
    assert "douyin" not in keys
