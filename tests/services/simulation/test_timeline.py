"""时间线管理器测试"""

import pytest
from datetime import datetime
from app.services.simulation.timeline import (
    Timeline, SimulationTick, TimelineEvent
)


class TestTimeline:
    """时间线测试"""

    def test_initialization_72h(self):
        """测试72小时初始化"""
        timeline = Timeline(duration="72h")

        assert timeline.total_hours == 72
        assert timeline.total_days == 3
        assert timeline.current_tick == 0
        assert timeline.progress == 0.0
        assert not timeline.is_complete

    def test_initialization_24h(self):
        """测试24小时初始化"""
        timeline = Timeline(duration="24h")

        assert timeline.total_hours == 24
        assert timeline.total_days == 1

    def test_initialization_7d(self):
        """测试7天初始化"""
        timeline = Timeline(duration="7d")

        assert timeline.total_hours == 168
        assert timeline.total_days == 7

    def test_advance_single_tick(self):
        """测试推进单个刻度"""
        timeline = Timeline(duration="72h")
        tick = timeline.advance()

        assert tick is not None
        assert tick.tick == 0
        assert timeline.current_tick == 1

    def test_advance_to_completion(self):
        """测试推进到完成"""
        timeline = Timeline(duration="3h")

        ticks = []
        while not timeline.is_complete:
            tick = timeline.advance()
            if tick:
                ticks.append(tick)

        assert len(ticks) == 3
        assert timeline.is_complete
        assert timeline.progress == 1.0

        # 完成后继续推进返回None
        assert timeline.advance() is None

    def test_hour_wrapping(self):
        """测试小时循环"""
        start = datetime(2024, 1, 1, 22, 0)  # 22:00
        timeline = Timeline(duration="5h", start_time=start)

        hours = []
        while not timeline.is_complete:
            tick = timeline.advance()
            if tick:
                hours.append(tick.hour)

        # 22, 23, 0, 1, 2
        assert hours == [22, 23, 0, 1, 2]

    def test_day_progression(self):
        """测试天数推进"""
        start = datetime(2024, 1, 1, 22, 0)  # 22:00
        timeline = Timeline(duration="5h", start_time=start)

        days = []
        while not timeline.is_complete:
            tick = timeline.advance()
            if tick:
                days.append(tick.day)

        # 0, 0, 1, 1, 1 (第三个小时跨天)
        assert days == [0, 0, 1, 1, 1]

    def test_add_event(self):
        """测试添加事件"""
        timeline = Timeline(duration="24h")
        timeline.advance()

        event = timeline.add_event(
            event_type="viral_post",
            event_data={"post_id": "post-123", "reach": 10000}
        )

        assert event.event_type == "viral_post"
        assert event.event_data["post_id"] == "post-123"
        assert len(timeline.events) == 1

    def test_get_events_by_type(self):
        """测试按类型获取事件"""
        timeline = Timeline(duration="24h")
        timeline.advance()

        timeline.add_event("viral_post", {"id": "1"})
        timeline.add_event("stance_change", {"id": "2"})
        timeline.add_event("viral_post", {"id": "3"})

        viral_posts = timeline.get_events_by_type("viral_post")
        assert len(viral_posts) == 2

    def test_get_events_by_day(self):
        """测试按天获取事件"""
        start = datetime(2024, 1, 1, 22, 0)
        timeline = Timeline(duration="26h", start_time=start)

        # 推进并添加事件
        for _ in range(26):
            timeline.advance()

        timeline.add_event("test", {"id": "1"}, tick=0)   # Day 0
        timeline.add_event("test", {"id": "2"}, tick=2)   # Day 1
        timeline.add_event("test", {"id": "3"}, tick=3)   # Day 1

        day0_events = timeline.get_events_by_day(0)
        day1_events = timeline.get_events_by_day(1)

        assert len(day0_events) == 1
        assert len(day1_events) == 2

    def test_get_summary(self):
        """测试获取摘要"""
        timeline = Timeline(duration="72h")
        summary = timeline.get_summary()

        assert summary["duration"] == "72h"
        assert summary["total_hours"] == 72
        assert summary["progress"] == 0.0

    def test_reset(self):
        """测试重置"""
        timeline = Timeline(duration="24h")

        # 推进一些
        for _ in range(5):
            timeline.advance()

        assert timeline.current_tick == 5

        # 重置
        timeline.reset()

        assert timeline.current_tick == 0
        assert len(timeline.ticks) == 0
        assert len(timeline.events) == 0

    def test_progress_calculation(self):
        """测试进度计算"""
        timeline = Timeline(duration="100h")

        assert timeline.progress == 0.0

        for _ in range(50):
            timeline.advance()

        assert timeline.progress == 0.5

        for _ in range(50):
            timeline.advance()

        assert timeline.progress == 1.0

    def test_current_datetime(self):
        """测试当前模拟时间"""
        start = datetime(2024, 1, 1, 12, 0)
        timeline = Timeline(duration="24h", start_time=start)

        assert timeline.current_datetime == start

        timeline.advance()
        assert timeline.current_datetime.hour == 13

    def test_get_tick(self):
        """测试获取指定刻度"""
        timeline = Timeline(duration="10h")

        for _ in range(5):
            timeline.advance()

        tick = timeline.get_tick(2)
        assert tick is not None
        assert tick.tick == 2

        # 超出范围
        assert timeline.get_tick(100) is None

    def test_invalid_duration_format(self):
        """测试无效时长格式"""
        with pytest.raises(ValueError):
            Timeline(duration="invalid")


class TestSimulationTick:
    """时间刻度测试"""

    def test_tick_creation(self):
        """测试刻度创建"""
        tick = SimulationTick(
            tick=5,
            hour=14,
            day=0,
            datetime_sim=datetime(2024, 1, 1, 14, 0),
        )

        assert tick.tick == 5
        assert tick.hour == 14
        assert tick.day == 0
        assert tick.actions_count == 0

    def test_tick_with_stats(self):
        """测试带统计的刻度"""
        tick = SimulationTick(
            tick=10,
            hour=10,
            day=0,
            datetime_sim=datetime(2024, 1, 1, 10, 0),
            actions_count=50,
            active_agents=20,
            posts=10,
            reposts=15,
            comments=20,
            likes=5,
        )

        assert tick.actions_count == 50
        assert tick.active_agents == 20
        assert tick.posts == 10

    def test_tick_with_events(self):
        """测试带事件的刻度"""
        event = TimelineEvent(
            tick=0,
            hour=10,
            day=0,
            timestamp=datetime(2024, 1, 1, 10, 0),
            event_type="test",
            event_data={"key": "value"},
        )

        tick = SimulationTick(
            tick=0,
            hour=10,
            day=0,
            datetime_sim=datetime(2024, 1, 1, 10, 0),
            events=[event],
        )

        assert len(tick.events) == 1
        assert tick.events[0].event_type == "test"


class TestTimelineEvent:
    """时间线事件测试"""

    def test_event_creation(self):
        """测试事件创建"""
        event = TimelineEvent(
            tick=5,
            hour=14,
            day=0,
            timestamp=datetime(2024, 1, 1, 14, 0),
            event_type="viral_post",
            event_data={"post_id": "123", "reach": 10000},
        )

        assert event.tick == 5
        assert event.event_type == "viral_post"
        assert event.event_data["post_id"] == "123"

    def test_event_default_data(self):
        """测试事件默认数据"""
        event = TimelineEvent(
            tick=0,
            hour=0,
            day=0,
            timestamp=datetime(2024, 1, 1, 0, 0),
            event_type="test",
        )

        assert event.event_data == {}
