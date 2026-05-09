"""模拟API Schema"""

from typing import Optional
from pydantic import BaseModel, Field
from app.services.simulation.models import (
    Platform, SimulationMode, RoleType, Stance,
    Persona, SeedMaterial, Simulation, SimulationResult
)


class SimulationStartRequest(BaseModel):
    """启动模拟请求"""
    mode: SimulationMode = SimulationMode.INDEPENDENT

    # 独立模式专用
    seed_content: Optional[str] = None
    seed_source_type: Optional[str] = "text"
    enable_research: bool = False

    # 配置
    agent_count: int = Field(ge=100, le=1000, default=500)
    platforms: list[Platform] = Field(default_factory=lambda: [Platform.WEIBO])
    duration: str = "72h"

    # 随机种子（用于可复现模拟）
    seed: Optional[int] = None

    # 名称
    name: str = ""
    description: str = ""


class SimulationStartResponse(BaseModel):
    """启动模拟响应"""
    simulation_id: str
    status: str
    message: str


class SimulationStatusResponse(BaseModel):
    """模拟状态响应"""
    simulation_id: str
    status: str
    progress: float = 0.0
    message: str = ""


class SimulationResultResponse(BaseModel):
    """模拟结果响应"""
    simulation_id: str
    status: str
    result: Optional[SimulationResult] = None
    created_at: str
    completed_at: Optional[str] = None


class PersonaTemplateCreate(BaseModel):
    """创建人格模板"""
    name: str
    description: str = ""
    role_type: RoleType = RoleType.NORMAL
    big_five: Optional[dict] = None
    influence_range: tuple[float, float] = (0.1, 0.5)
    activity_range: tuple[float, float] = (0.3, 0.7)
    default_stance: Stance = Stance.NEUTRAL
    language_style: str = "neutral"
    is_public: bool = False


class SimulationListQuery(BaseModel):
    """模拟列表查询"""
    page: int = 1
    page_size: int = 20
    mode: Optional[SimulationMode] = None
    status: Optional[str] = None
    tags: Optional[list[str]] = None
