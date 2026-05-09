"""时间线管理器 - 管理模拟时间推进"""

from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum


class SimulationTimeUnit(str, Enum):
    """模拟时间单位"""
    HOUR = "hour"
    DAY = "day"


@dataclass
class TimelineEvent:
    """时间线事件"""
    tick: int  # 时间刻度
    hour: int  # 实际小时（0-23）
    day: int   # 模拟天数
    timestamp: datetime
    event_type: str
    event_data: dict = field(default_factory=dict)


@dataclass
class SimulationTick:
    """单个时间刻度的状态"""
    tick: int
    hour: int  # 0-23
    day: int
    datetime_sim: datetime  # 模拟中的时间点

    # 该时刻的统计数据
    actions_count: int = 0
    active_agents: int = 0
    posts: int = 0
    reposts: int = 0
    comments: int = 0
    likes: int = 0

    # 立场变化
    stance_changes: list[dict] = field(default_factory=list)

    # 关键事件
    events: list[TimelineEvent] = field(default_factory=list)


class Timeline:
    """模拟时间线管理器"""

    def __init__(
        self,
        duration: str = "72h",
        start_time: Optional[datetime] = None,
    ):
        """
        初始化时间线

        Args:
            duration: 模拟时长，格式为 "24h", "72h", "7d"
            start_time: 起始时间，默认为当前时间
        """
        self.duration = duration
        self.start_time = start_time or datetime.now()

        # 解析时长
        self.total_hours = self._parse_duration(duration)
        self.total_days = self.total_hours // 24

        # 当前状态
        self.current_tick = 0
        self.current_hour = self.start_time.hour
        self.current_day = 0

        # 时间线历史
        self.ticks: list[SimulationTick] = []

        # 事件记录
        self.events: list[TimelineEvent] = []

    def _parse_duration(self, duration: str) -> int:
        """解析时长字符串为小时数"""
        if duration.endswith("h"):
            return int(duration[:-1])
        elif duration.endswith("d"):
            return int(duration[:-1]) * 24
        else:
            raise ValueError(f"Invalid duration format: {duration}")

    @property
    def progress(self) -> float:
        """当前进度 (0.0 - 1.0)"""
        return self.current_tick / self.total_hours if self.total_hours > 0 else 0.0

    @property
    def is_complete(self) -> bool:
        """是否已完成"""
        return self.current_tick >= self.total_hours

    @property
    def current_datetime(self) -> datetime:
        """当前模拟时间"""
        return self.start_time + timedelta(hours=self.current_tick)

    def advance(self) -> Optional[SimulationTick]:
        """
        推进一个时间刻度（1小时）

        Returns:
            当前刻度的状态，如果已完成则返回None
        """
        if self.is_complete:
            return None

        # 创建当前刻度
        tick = SimulationTick(
            tick=self.current_tick,
            hour=self.current_hour,
            day=self.current_day,
            datetime_sim=self.current_datetime,
        )

        self.ticks.append(tick)

        # 更新状态
        self.current_tick += 1
        self.current_hour = (self.current_hour + 1) % 24

        # 新的一天
        if self.current_hour == 0:
            self.current_day += 1

        return tick

    def get_tick(self, tick_index: int) -> Optional[SimulationTick]:
        """获取指定刻度的状态"""
        if 0 <= tick_index < len(self.ticks):
            return self.ticks[tick_index]
        return None

    def add_event(
        self,
        event_type: str,
        event_data: dict,
        tick: Optional[int] = None,
    ) -> TimelineEvent:
        """添加事件到时间线"""
        tick_num = tick if tick is not None else self.current_tick

        # Calculate actual hour and day based on start time
        actual_hour = (self.start_time.hour + tick_num) % 24
        # Day is calculated by how many times we've crossed midnight
        day = (self.start_time.hour + tick_num) // 24

        event = TimelineEvent(
            tick=tick_num,
            hour=actual_hour,
            day=day,
            timestamp=self.start_time + timedelta(hours=tick_num),
            event_type=event_type,
            event_data=event_data,
        )

        self.events.append(event)

        # 同时添加到对应刻度
        if tick_num < len(self.ticks):
            self.ticks[tick_num].events.append(event)

        return event

    def get_events_by_type(self, event_type: str) -> list[TimelineEvent]:
        """按类型获取事件"""
        return [e for e in self.events if e.event_type == event_type]

    def get_events_by_day(self, day: int) -> list[TimelineEvent]:
        """按天获取事件"""
        return [e for e in self.events if e.day == day]

    def get_summary(self) -> dict:
        """获取时间线摘要"""
        return {
            "duration": self.duration,
            "total_hours": self.total_hours,
            "total_days": self.total_days,
            "current_tick": self.current_tick,
            "progress": self.progress,
            "is_complete": self.is_complete,
            "total_events": len(self.events),
            "start_time": self.start_time.isoformat(),
            "end_time": (self.start_time + timedelta(hours=self.total_hours)).isoformat(),
        }

    def reset(self):
        """重置时间线"""
        self.current_tick = 0
        self.current_hour = self.start_time.hour
        self.current_day = 0
        self.ticks.clear()
        self.events.clear()
