"""数据模型定义"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum


class Platform(str, Enum):
    """支持的平台"""
    WEIBO = "weibo"
    XIAOHONGSHU = "xiaohongshu"
    DOUYIN = "douyin"
    BILIBILI = "bilibili"


class RoleType(str, Enum):
    """Agent角色类型"""
    NORMAL = "normal"           # 普通网友
    RATIONAL = "rational"       # 理性分析派
    KOL = "kol"                 # KOL/意见领袖
    EXTREME = "extreme"         # 极端粉丝
    BYSTANDER = "bystander"     # 吃瓜群众
    OFFICIAL = "official"       # 官方/媒体号
    TROLL = "troll"             # 专业黑/职业喷
    NOVICE = "novice"           # 萌新/小白


class Stance(str, Enum):
    """立场倾向"""
    SUPPORT = "support"         # 支持
    OPPOSE = "oppose"           # 反对
    NEUTRAL = "neutral"         # 中立
    FICKLE = "fickle"           # 墙头草


class UserType(str, Enum):
    """用户类型"""
    CORE = "core"               # 核心用户(高影响力)
    ORDINARY = "ordinary"       # 普通用户


class SimulationMode(str, Enum):
    """模拟模式"""
    DEEP_RESEARCH = "deep_research"   # 深度推演
    INDEPENDENT = "independent"        # 独立模拟


class SimulationStatus(str, Enum):
    """模拟状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BigFive(BaseModel):
    """Big Five人格模型"""
    openness: float = Field(ge=0, le=1, default=0.5)
    conscientiousness: float = Field(ge=0, le=1, default=0.5)
    extraversion: float = Field(ge=0, le=1, default=0.5)
    agreeableness: float = Field(ge=0, le=1, default=0.5)
    neuroticism: float = Field(ge=0, le=1, default=0.5)


class TemporalPattern(BaseModel):
    """时间活跃模式（24小时向量）"""
    pattern: list[float] = Field(default_factory=lambda: [0.0] * 24)

    @classmethod
    def create_workday(cls) -> "TemporalPattern":
        """工作日模式：白天活跃"""
        pattern = [0.0] * 24
        for i in range(6, 9):
            pattern[i] = 0.3 + (i - 6) * 0.1
        for i in range(9, 12):
            pattern[i] = 0.7
        for i in range(12, 14):
            pattern[i] = 0.5
        for i in range(14, 18):
            pattern[i] = 0.7
        for i in range(18, 22):
            pattern[i] = 0.6
        for i in range(22, 24):
            pattern[i] = 0.3
        return cls(pattern=pattern)

    @classmethod
    def create_night_owl(cls) -> "TemporalPattern":
        """夜猫子模式：晚上活跃"""
        pattern = [0.0] * 24
        for i in range(20, 24):
            pattern[i] = 0.5 + (i - 20) * 0.15
        for i in range(0, 2):
            pattern[i] = 0.8
        for i in range(2, 6):
            pattern[i] = 0.3
        return cls(pattern=pattern)


class Persona(BaseModel):
    """Agent人格"""
    id: str
    name: str
    username: str
    avatar: str = ""
    bio: str = ""

    # 角色配置
    role_type: RoleType = RoleType.NORMAL
    platform: Platform = Platform.WEIBO

    # Big Five
    big_five: BigFive = Field(default_factory=BigFive)

    # 立场
    stance: Stance = Stance.NEUTRAL
    stance_flexibility: float = Field(ge=0, le=1, default=0.5)

    # 行为参数
    influence: float = Field(ge=0, le=1, default=0.3)
    activity: float = Field(ge=0, le=1, default=0.5)
    conformity: float = Field(ge=0, le=1, default=0.5)
    expertise: float = Field(ge=0, le=1, default=0.3)

    # 时间特征
    temporal_pattern: TemporalPattern = Field(default_factory=TemporalPattern)

    # 社交属性
    user_type: UserType = UserType.ORDINARY
    follower_count: int = 0

    # 职业
    profession: str = ""
    profession_category: str = ""

    # 发言风格
    language_style: str = "neutral"  # professional/casual/emotional/rational
    topics_of_interest: list[str] = Field(default_factory=list)
    typical_statements: list[str] = Field(default_factory=list)


class SeedMaterial(BaseModel):
    """种子材料"""
    id: str
    content: str
    source_type: Literal["text", "url", "document"] = "text"
    source_url: Optional[str] = None
    research_summary: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class AgentAction(BaseModel):
    """Agent交互动作"""
    id: str
    agent_id: str
    action_type: str  # post/repost/comment/like/follow
    target_agent_id: Optional[str] = None
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)
    platform: Platform = Platform.WEIBO


class SimulationResult(BaseModel):
    """模拟结果"""
    # 情绪统计
    sentiment_distribution: dict[str, float] = Field(default_factory=dict)

    # 观点聚类
    opinion_clusters: list[dict] = Field(default_factory=list)

    # 引爆点
    trigger_points: list[dict] = Field(default_factory=list)

    # 风险预警
    risk_warnings: list[str] = Field(default_factory=list)

    # 建议
    suggestions: list[str] = Field(default_factory=list)

    # 图数据
    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)


class Simulation(BaseModel):
    """模拟记录"""
    id: str
    name: str = ""
    description: str = ""

    # 模式
    mode: SimulationMode = SimulationMode.INDEPENDENT

    # 配置
    agent_count: int = 500
    platforms: list[Platform] = Field(default_factory=lambda: [Platform.WEIBO])
    duration: str = "72h"

    # 种子材料
    seed_id: Optional[str] = None
    seed_content: str = ""

    # 状态
    status: SimulationStatus = SimulationStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # 结果
    result: Optional[SimulationResult] = None

    # 存储路径
    storage_path: str = ""

    # 标签
    tags: list[str] = Field(default_factory=list)
