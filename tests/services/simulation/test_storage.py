"""存储测试"""

import pytest
import os
import tempfile
import shutil
from datetime import datetime
from app.services.simulation.models import Simulation, SimulationResult, Platform, SimulationStatus
from app.services.simulation.storage import SimulationStorage


@pytest.fixture
def temp_storage():
    """临时存储"""
    temp_dir = tempfile.mkdtemp()
    storage = SimulationStorage(base_path=temp_dir)
    yield storage
    shutil.rmtree(temp_dir)


def test_save_and_get_simulation(temp_storage):
    """测试保存和获取"""
    sim = Simulation(
        id="test-sim-001",
        name="测试模拟",
        seed_content="测试内容",
        agent_count=100,
        platforms=[Platform.WEIBO],
        status=SimulationStatus.COMPLETED
    )
    sim.completed_at = datetime.now()

    # 保存
    path = temp_storage.save_simulation(sim)
    assert os.path.exists(path)

    # 获取
    loaded = temp_storage.get_simulation("test-sim-001")
    assert loaded is not None
    assert loaded.id == sim.id
    assert loaded.name == "测试模拟"


def test_list_simulations(temp_storage):
    """测试列表查询"""
    # 创建多个模拟
    for i in range(5):
        sim = Simulation(
            id=f"test-sim-{i}",
            name=f"测试模拟{i}",
            seed_content=f"内容{i}",
            status=SimulationStatus.COMPLETED
        )
        sim.completed_at = datetime.now()
        temp_storage.save_simulation(sim)

    # 列表查询
    results, total = temp_storage.list_simulations(page=1, page_size=10)
    assert total == 5
    assert len(results) == 5


def test_delete_simulation(temp_storage):
    """测试删除"""
    sim = Simulation(
        id="test-delete-001",
        name="删除测试",
        seed_content="内容"
    )
    temp_storage.save_simulation(sim)

    # 删除
    assert temp_storage.delete_simulation("test-delete-001") is True
    assert temp_storage.get_simulation("test-delete-001") is None
