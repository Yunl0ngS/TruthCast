"""模拟系统配置"""

import os
from typing import Optional
from pydantic import BaseModel


class SimulationConfig(BaseModel):
    """模拟系统配置"""

    # Agent配置
    default_agent_count: int = 500
    min_agent_count: int = 100
    max_agent_count: int = 1000

    # 平台配置
    default_platforms: list[str] = ["weibo", "xiaohongshu"]
    supported_platforms: list[str] = ["weibo", "xiaohongshu", "douyin", "bilibili"]

    # 时间配置
    default_duration: str = "72h"
    duration_options: list[str] = ["24h", "72h", "7d"]

    # LLM配置
    llm_enabled: bool = os.getenv("TRUTHCAST_SIMULATION_LLM_ENABLED", "false").lower() == "true"
    llm_model: str = os.getenv("TRUTHCAST_SIMULATION_LLM_MODEL", "")
    llm_base_url: str = os.getenv("TRUTHCAST_SIMULATION_LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.getenv("TRUTHCAST_SIMULATION_LLM_API_KEY", "")
    llm_timeout: int = int(os.getenv("TRUTHCAST_SIMULATION_LLM_TIMEOUT", "45"))

    # 存储配置
    storage_path: str = os.getenv("TRUTHCAST_SIMULATION_STORAGE", "data/simulations")

    # 调研配置
    research_enabled: bool = True
    research_max_sources: int = 15


# 全局配置实例
_config: Optional[SimulationConfig] = None


def get_simulation_config() -> SimulationConfig:
    """获取模拟配置"""
    global _config
    if _config is None:
        _config = SimulationConfig()
    return _config
