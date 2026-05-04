"""数据模型测试"""

import pytest
from app.services.simulation.models import (
    Persona, SeedMaterial, Simulation, Platform,
    RoleType, Stance, BigFive, TemporalPattern
)


def test_persona_creation():
    """测试Persona创建"""
    persona = Persona(
        id="test-001",
        name="测试用户",
        username="test_user",
        role_type=RoleType.NORMAL,
        platform=Platform.WEIBO
    )
    assert persona.id == "test-001"
    assert persona.role_type == RoleType.NORMAL


def test_temporal_pattern_workday():
    """测试工作日时间模式"""
    pattern = TemporalPattern.create_workday()
    assert len(pattern.pattern) == 24
    assert pattern.pattern[9] > pattern.pattern[3]  # 白天比凌晨活跃


def test_simulation_creation():
    """测试Simulation创建"""
    sim = Simulation(
        id="sim-001",
        name="测试模拟",
        seed_content="测试内容"
    )
    assert sim.id == "sim-001"
    assert sim.status.value == "pending"
