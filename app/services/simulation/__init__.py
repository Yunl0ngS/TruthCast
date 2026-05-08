"""多Agent舆情模拟服务"""

from app.services.simulation.config import SimulationConfig, get_simulation_config
from app.services.simulation.models import (
    SeedMaterial, Persona, Simulation, SimulationResult,
    Platform, RoleType, Stance, UserType, SimulationMode, SimulationStatus,
    BigFive, TemporalPattern, AgentAction,
)
from app.services.simulation.storage import SimulationStorage, get_simulation_storage
from app.services.simulation.persona_factory import PersonaFactory, create_agent_pool
from app.services.simulation.persona_templates import (
    ROLE_CONFIGS, PROFESSION_CATEGORIES,
    FIRST_NAMES_MALE, FIRST_NAMES_FEMALE, LAST_NAMES,
    USERNAME_PREFIXES, BIO_TEMPLATES, RoleConfig, ProfessionCategory
)
from app.services.simulation.action_engine import ActionEngine, ActionContext
from app.services.simulation.platform_simulator import (
    PlatformSimulator, MultiPlatformSimulator,
    PlatformAdapter, WeiboAdapter, XiaohongshuAdapter, DouyinAdapter, BilibiliAdapter,
    PlatformState, PLATFORM_ADAPTERS
)

__all__ = [
    # Config
    "SimulationConfig",
    "get_simulation_config",

    # Models
    "SeedMaterial",
    "Persona",
    "Simulation",
    "SimulationResult",
    "Platform",
    "RoleType",
    "Stance",
    "UserType",
    "SimulationMode",
    "SimulationStatus",
    "BigFive",
    "TemporalPattern",
    "AgentAction",

    # Storage
    "SimulationStorage",
    "get_simulation_storage",

    # Persona Factory
    "PersonaFactory",
    "create_agent_pool",
    "ROLE_CONFIGS",
    "PROFESSION_CATEGORIES",
    "RoleConfig",
    "ProfessionCategory",
    "FIRST_NAMES_MALE",
    "FIRST_NAMES_FEMALE",
    "LAST_NAMES",
    "USERNAME_PREFIXES",
    "BIO_TEMPLATES",

    # Action Engine
    "ActionEngine",
    "ActionContext",

    # Platform Simulator
    "PlatformSimulator",
    "MultiPlatformSimulator",
    "PlatformAdapter",
    "WeiboAdapter",
    "XiaohongshuAdapter",
    "DouyinAdapter",
    "BilibiliAdapter",
    "PlatformState",
    "PLATFORM_ADAPTERS",
]
