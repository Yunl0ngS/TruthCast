"""模拟系统数据模型"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    """支持的社交平台"""
    WEIBO = "weibo"
    XIAOHONGSHU = "xiaohongshu"
    DOUYIN = "douyin"
    BILIBILI = "bilibili"


class SimulationStatus(str, Enum):
    """模拟状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SeedMaterial(BaseModel):
    """种子素材"""
    id: str
    title: str
    content: str
    source_url: Optional[str] = None
    source_platform: Optional[Platform] = None
    created_at: datetime = Field(default_factory=datetime.now)


class Persona(BaseModel):
    """Agent人设"""
    id: str
    name: str
    role: str
    age_range: str
    occupation: str
    personality: str
    platform_preference: list[Platform]
    influence_score: float = Field(ge=0.0, le=1.0)
    activity_level: float = Field(ge=0.0, le=1.0)


class Simulation(BaseModel):
    """模拟实例"""
    id: str
    seed_material_id: str
    agent_count: int
    duration: str
    platforms: list[Platform]
    status: SimulationStatus = SimulationStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SimulationResult(BaseModel):
    """模拟结果"""
    simulation_id: str
    total_posts: int = 0
    total_comments: int = 0
    total_shares: int = 0
    sentiment_distribution: dict[str, int] = Field(default_factory=dict)
    topic_keywords: list[str] = Field(default_factory=list)
    influence_metrics: dict[str, float] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=datetime.now)
