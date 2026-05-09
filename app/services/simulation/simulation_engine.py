"""模拟引擎核心 - 整合所有组件执行完整模拟"""

import asyncio
import uuid
from typing import Optional, AsyncGenerator
from datetime import datetime
from dataclasses import dataclass

from app.services.simulation.models import (
    Persona, Simulation, SimulationResult, SimulationStatus,
    Platform, Stance
)
from app.services.simulation.config import get_simulation_config
from app.services.simulation.storage import get_simulation_storage
from app.services.simulation.persona_factory import PersonaFactory
from app.services.simulation.platform_simulator import MultiPlatformSimulator
from app.services.simulation.timeline import Timeline
from app.services.simulation.report_generator import ReportGenerator


@dataclass
class SimulationProgress:
    """模拟进度"""
    simulation_id: str
    tick: int
    total_ticks: int
    progress: float
    current_hour: int
    current_day: int
    status: str
    message: str


class SimulationEngine:
    """模拟引擎"""

    def __init__(
        self,
        simulation_id: str,
        agent_count: int = 500,
        platforms: Optional[list[Platform]] = None,
        duration: str = "72h",
        seed_content: str = "",
        seed: Optional[int] = None,
    ):
        """
        初始化模拟引擎

        Args:
            simulation_id: 模拟ID
            agent_count: Agent数量
            platforms: 平台列表
            duration: 模拟时长
            seed_content: 种子材料内容
            seed: 随机种子
        """
        self.simulation_id = simulation_id
        self.agent_count = agent_count
        self.platforms = platforms or [Platform.WEIBO]
        self.duration = duration
        self.seed_content = seed_content
        self.seed = seed

        # 初始化组件
        self.factory = PersonaFactory(seed=seed)
        self.timeline = Timeline(duration=duration)
        self.report_generator = ReportGenerator()

        # Agent池
        self.agents: list[Persona] = []
        self.agents_by_platform: dict[Platform, list[Persona]] = {}

        # 平台模拟器
        self.simulator = MultiPlatformSimulator(self.platforms, seed=seed)

        # 种子关键词（从内容提取）
        self.seed_keywords = self._extract_keywords(seed_content)

        # 状态
        self.is_running = False
        self.is_paused = False

    def _extract_keywords(self, content: str) -> list[str]:
        """提取关键词（简化版）"""
        if not content:
            return ["话题"]

        # 简单分词和关键词提取
        # 实际应该使用NLP工具
        words = content.split()
        keywords = [w for w in words if len(w) >= 2][:5]
        return keywords if keywords else ["话题"]

    def _create_agents(self):
        """创建Agent池"""
        # 根据平台分配Agent
        agents_per_platform = self.agent_count // len(self.platforms)

        for platform in self.platforms:
            platform_agents = self.factory.create_batch(
                count=agents_per_platform,
                platform=platform,
            )
            self.agents.extend(platform_agents)
            self.agents_by_platform[platform] = platform_agents

        # 处理剩余
        remaining = self.agent_count - len(self.agents)
        if remaining > 0:
            extra_agents = self.factory.create_batch(
                count=remaining,
                platform=self.platforms[0],
            )
            self.agents.extend(extra_agents)
            self.agents_by_platform[self.platforms[0]].extend(extra_agents)

    async def run(self) -> SimulationResult:
        """
        运行完整模拟

        Returns:
            模拟结果
        """
        self.is_running = True

        # 创建Agent
        self._create_agents()

        # 时间线推进
        while not self.timeline.is_complete:
            # 检查暂停
            while self.is_paused:
                await asyncio.sleep(0.1)

            if not self.is_running:
                break

            # 推进一个时刻
            tick = self.timeline.advance()
            if tick is None:
                break

            # 各平台模拟
            actions_by_platform = self.simulator.simulate_tick(
                agents_by_platform=self.agents_by_platform,
                current_hour=tick.hour,
                seed_keywords=self.seed_keywords,
            )

            # 收集所有行动
            all_actions = []
            for platform_actions in actions_by_platform.values():
                all_actions.extend(platform_actions)

            # 更新刻度统计
            tick.actions_count = len(all_actions)
            tick.active_agents = len(set(a.agent_id for a in all_actions))
            tick.posts = sum(1 for a in all_actions if a.action_type == "post")
            tick.reposts = sum(1 for a in all_actions if a.action_type == "repost")
            tick.comments = sum(1 for a in all_actions if a.action_type == "comment")
            tick.likes = sum(1 for a in all_actions if a.action_type == "like")

            # 记录到报告生成器
            self.report_generator.record_tick(tick, self.agents, all_actions)

            # 模拟真实时间流逝（可配置）
            await asyncio.sleep(0.01)  # 10ms per tick

        self.is_running = False

        # 生成最终报告
        return self.report_generator.generate_result()

    async def run_with_progress(self) -> AsyncGenerator[SimulationProgress, None]:
        """
        带进度回调的模拟

        Yields:
            模拟进度
        """
        self.is_running = True

        # 创建Agent
        self._create_agents()

        # 初始进度
        yield SimulationProgress(
            simulation_id=self.simulation_id,
            tick=0,
            total_ticks=self.timeline.total_hours,
            progress=0.0,
            current_hour=self.timeline.current_hour,
            current_day=0,
            status="running",
            message="初始化完成，开始模拟",
        )

        # 时间线推进
        while not self.timeline.is_complete:
            # 检查暂停
            while self.is_paused:
                await asyncio.sleep(0.1)

            if not self.is_running:
                yield SimulationProgress(
                    simulation_id=self.simulation_id,
                    tick=self.timeline.current_tick,
                    total_ticks=self.timeline.total_hours,
                    progress=self.timeline.progress,
                    current_hour=self.timeline.current_hour,
                    current_day=self.timeline.current_day,
                    status="cancelled",
                    message="模拟已取消",
                )
                break

            # 推进一个时刻
            tick = self.timeline.advance()
            if tick is None:
                break

            # 各平台模拟
            actions_by_platform = self.simulator.simulate_tick(
                agents_by_platform=self.agents_by_platform,
                current_hour=tick.hour,
                seed_keywords=self.seed_keywords,
            )

            # 收集所有行动
            all_actions = []
            for platform_actions in actions_by_platform.values():
                all_actions.extend(platform_actions)

            # 更新刻度统计
            tick.actions_count = len(all_actions)

            # 记录到报告生成器
            self.report_generator.record_tick(tick, self.agents, all_actions)

            # 返回进度
            yield SimulationProgress(
                simulation_id=self.simulation_id,
                tick=self.timeline.current_tick,
                total_ticks=self.timeline.total_hours,
                progress=self.timeline.progress,
                current_hour=tick.hour,
                current_day=tick.day,
                status="running",
                message=f"正在模拟第{tick.day + 1}天 {tick.hour}:00",
            )

            # 模拟真实时间流逝
            await asyncio.sleep(0.01)

        self.is_running = False

        # 最终进度
        yield SimulationProgress(
            simulation_id=self.simulation_id,
            tick=self.timeline.total_hours,
            total_ticks=self.timeline.total_hours,
            progress=1.0,
            current_hour=(self.timeline.start_time.hour + self.timeline.total_hours) % 24,
            current_day=self.timeline.total_days,
            status="completed",
            message="模拟完成",
        )

    def pause(self):
        """暂停模拟"""
        self.is_paused = True

    def resume(self):
        """恢复模拟"""
        self.is_paused = False

    def cancel(self):
        """取消模拟"""
        self.is_running = False
        self.is_paused = False

    def get_intermediate_result(self) -> SimulationResult:
        """获取中间结果"""
        return self.report_generator.generate_result()

    def get_statistics(self) -> dict:
        """获取当前统计"""
        return {
            "simulation_id": self.simulation_id,
            "agent_count": len(self.agents),
            "platforms": [p.value for p in self.platforms],
            "duration": self.duration,
            "progress": self.timeline.progress,
            "current_tick": self.timeline.current_tick,
            "total_ticks": self.timeline.total_hours,
            "is_running": self.is_running,
            "is_paused": self.is_paused,
            "platform_stats": self.simulator.get_all_statistics(),
        }


async def run_simulation(
    simulation_id: str,
    agent_count: int = 500,
    platforms: Optional[list[Platform]] = None,
    duration: str = "72h",
    seed_content: str = "",
    seed: Optional[int] = None,
) -> SimulationResult:
    """
    运行模拟的便捷函数

    Args:
        simulation_id: 模拟ID
        agent_count: Agent数量
        platforms: 平台列表
        duration: 模拟时长
        seed_content: 种子材料
        seed: 随机种子

    Returns:
        模拟结果
    """
    engine = SimulationEngine(
        simulation_id=simulation_id,
        agent_count=agent_count,
        platforms=platforms,
        duration=duration,
        seed_content=seed_content,
        seed=seed,
    )
    return await engine.run()
