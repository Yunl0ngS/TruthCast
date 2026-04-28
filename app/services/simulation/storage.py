"""模拟系统持久化存储"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List
from app.services.simulation.models import Simulation, SimulationResult, Platform
from app.services.simulation.config import get_simulation_config


class SimulationStorage:
    """模拟存储服务"""

    def __init__(self, base_path: Optional[str] = None):
        config = get_simulation_config()
        self.base_path = Path(base_path or config.storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _get_simulation_dir(self, simulation_id: str) -> Path:
        """获取模拟目录"""
        sim_dir = self.base_path / simulation_id
        sim_dir.mkdir(parents=True, exist_ok=True)
        return sim_dir

    def save_simulation(self, simulation: Simulation) -> str:
        """保存模拟记录"""
        sim_dir = self._get_simulation_dir(simulation.id)

        # 保存主配置
        config_file = sim_dir / "config.json"
        config_data = simulation.model_dump(exclude={"result"})
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2, default=str)

        # 保存结果（如果有）
        if simulation.result:
            result_file = sim_dir / "result.json"
            result_data = simulation.result.model_dump()
            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2, default=str)

        # 保存元数据
        metadata = {
            "id": simulation.id,
            "name": simulation.name,
            "created_at": simulation.created_at.isoformat(),
            "completed_at": simulation.completed_at.isoformat() if simulation.completed_at else None,
            "status": simulation.status.value,
            "tags": simulation.tags,
        }
        metadata_file = sim_dir / "metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        return str(sim_dir)

    def get_simulation(self, simulation_id: str) -> Optional[Simulation]:
        """获取模拟记录"""
        sim_dir = self.base_path / simulation_id
        if not sim_dir.exists():
            return None

        config_file = sim_dir / "config.json"
        if not config_file.exists():
            return None

        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 加载结果
        result = None
        result_file = sim_dir / "result.json"
        if result_file.exists():
            with open(result_file, "r", encoding="utf-8") as f:
                result_data = json.load(f)
                result = SimulationResult(**result_data)

        data["result"] = result
        return Simulation(**data)

    def list_simulations(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> tuple[List[Simulation], int]:
        """列出模拟记录"""
        simulations = []

        for sim_dir in sorted(self.base_path.iterdir(), key=lambda x: x.name, reverse=True):
            if not sim_dir.is_dir():
                continue

            metadata_file = sim_dir / "metadata.json"
            if not metadata_file.exists():
                continue

            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # 过滤
            if status and metadata.get("status") != status:
                continue
            if tags:
                sim_tags = set(metadata.get("tags", []))
                if not sim_tags.intersection(set(tags)):
                    continue

            # 加载完整记录
            simulation = self.get_simulation(sim_dir.name)
            if simulation:
                simulations.append(simulation)

        # 分页
        total = len(simulations)
        start = (page - 1) * page_size
        end = start + page_size
        return simulations[start:end], total

    def delete_simulation(self, simulation_id: str) -> bool:
        """删除模拟记录"""
        import shutil
        sim_dir = self.base_path / simulation_id
        if sim_dir.exists():
            shutil.rmtree(sim_dir)
            return True
        return False

    def save_graph_data(self, simulation_id: str, nodes: list, edges: list) -> None:
        """保存图数据"""
        sim_dir = self._get_simulation_dir(simulation_id)
        graph_dir = sim_dir / "graph"
        graph_dir.mkdir(exist_ok=True)

        with open(graph_dir / "nodes.json", "w", encoding="utf-8") as f:
            json.dump(nodes, f, ensure_ascii=False, indent=2)

        with open(graph_dir / "edges.json", "w", encoding="utf-8") as f:
            json.dump(edges, f, ensure_ascii=False, indent=2)


# 全局存储实例
_storage: Optional[SimulationStorage] = None


def get_simulation_storage() -> SimulationStorage:
    """获取存储实例"""
    global _storage
    if _storage is None:
        _storage = SimulationStorage()
    return _storage
