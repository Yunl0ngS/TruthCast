from pathlib import Path


def test_load_platform_configs_reads_yaml_and_filters_enabled(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
defaults:
  scan_interval_minutes: 60
  fetch_top_n: 10
  risk_snapshot_threshold: 40
  report_threshold_for_simulation: 50

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
    assert platforms[0].fetch_top_n == 10
    assert platforms[0].risk_snapshot_threshold == 40
    assert platforms[0].report_threshold_for_simulation == 50


def test_load_platform_configs_supports_env_overrides(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
defaults:
  scan_interval_minutes: 60
  fetch_top_n: 10
  risk_snapshot_threshold: 40
  report_threshold_for_simulation: 50

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
    monkeypatch.setenv('TRUTHCAST_MONITOR_PLATFORM_INTERVALS', '{"zhihu":30}')

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()

    assert [item.key for item in platforms] == ["zhihu"]
    assert platforms[0].newsnow_id == "zhihu-hot"
    assert platforms[0].scan_interval_minutes == 30
    assert platforms[0].fetch_top_n == 10


def test_load_platform_configs_prefers_platform_values_over_defaults(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "monitor_platforms.yaml"
    config_path.write_text(
        """
defaults:
  scan_interval_minutes: 60
  fetch_top_n: 10
  risk_snapshot_threshold: 40
  report_threshold_for_simulation: 50

platforms:
  - key: thepaper
    display_name: 澎湃新闻
    newsnow_id: thepaper
    enabled: true
    scan_interval_minutes: 30
    fetch_top_n: 20
    risk_snapshot_threshold: 55
    report_threshold_for_simulation: 65
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(config_path))

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platform = load_enabled_monitor_platforms()[0]

    assert platform.scan_interval_minutes == 30
    assert platform.fetch_top_n == 20
    assert platform.risk_snapshot_threshold == 55
    assert platform.report_threshold_for_simulation == 65


def test_load_platform_configs_falls_back_to_default_when_file_missing(monkeypatch) -> None:
    monkeypatch.setenv("TRUTHCAST_MONITOR_PLATFORM_CONFIG", str(Path("/tmp/not-exists-monitor-platforms.yaml")))

    from app.services.monitor.platform_config import load_enabled_monitor_platforms

    platforms = load_enabled_monitor_platforms()

    keys = {item.key for item in platforms}
    assert "thepaper" in keys
    assert "wallstreetcn-quick" in keys
    assert "zaobao" in keys
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

    assert keys == {"thepaper", "wallstreetcn-quick", "zaobao"}
    assert "weibo" not in keys
    assert "zhihu" not in keys
    assert "douyin" not in keys
