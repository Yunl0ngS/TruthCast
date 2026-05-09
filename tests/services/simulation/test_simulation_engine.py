"""模拟引擎测试"""

import pytest
import asyncio
from app.services.simulation.simulation_engine import (
    SimulationEngine, SimulationProgress, run_simulation
)
from app.services.simulation.models import Platform


class TestSimulationEngine:
    """模拟引擎测试"""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """测试初始化"""
        engine = SimulationEngine(
            simulation_id="test-sim-001",
            agent_count=100,
            platforms=[Platform.WEIBO],
            duration="3h",
        )

        assert engine.simulation_id == "test-sim-001"
        assert engine.agent_count == 100
        assert engine.duration == "3h"

    @pytest.mark.asyncio
    async def test_run_short_simulation(self):
        """测试运行短模拟"""
        engine = SimulationEngine(
            simulation_id="test-sim-002",
            agent_count=50,
            platforms=[Platform.WEIBO],
            duration="2h",  # 仅2小时
            seed_content="测试内容",
        )

        result = await engine.run()

        assert result is not None
        assert result.sentiment_distribution is not None

    @pytest.mark.asyncio
    async def test_run_with_progress(self):
        """测试带进度的模拟"""
        engine = SimulationEngine(
            simulation_id="test-sim-003",
            agent_count=30,
            platforms=[Platform.WEIBO],
            duration="2h",
        )

        progress_list = []
        async for progress in engine.run_with_progress():
            progress_list.append(progress)

        assert len(progress_list) >= 2  # 初始 + 结束
        assert progress_list[-1].status == "completed"
        assert progress_list[-1].progress == 1.0

    @pytest.mark.asyncio
    async def test_multi_platform(self):
        """测试多平台模拟"""
        engine = SimulationEngine(
            simulation_id="test-sim-004",
            agent_count=100,
            platforms=[Platform.WEIBO, Platform.XIAOHONGSHU],
            duration="2h",
        )

        result = await engine.run()

        assert len(engine.agents) == 100
        assert Platform.WEIBO in engine.agents_by_platform
        assert Platform.XIAOHONGSHU in engine.agents_by_platform

    @pytest.mark.asyncio
    async def test_pause_and_resume(self):
        """测试暂停和恢复"""
        engine = SimulationEngine(
            simulation_id="test-sim-005",
            agent_count=20,
            duration="5h",
        )

        # 在后台运行
        async def run_with_pause():
            progress_count = 0
            async for progress in engine.run_with_progress():
                progress_count += 1
                if progress.tick == 2:
                    engine.pause()
                    await asyncio.sleep(0.1)
                    engine.resume()
            return progress_count

        count = await run_with_pause()
        assert count > 0

    @pytest.mark.asyncio
    async def test_cancel(self):
        """测试取消"""
        engine = SimulationEngine(
            simulation_id="test-sim-006",
            agent_count=20,
            duration="100h",  # 长时间
        )

        cancelled = False
        async for progress in engine.run_with_progress():
            if progress.tick == 5:
                engine.cancel()
                cancelled = True
            if progress.status == "cancelled":
                break

        assert cancelled

    @pytest.mark.asyncio
    async def test_get_statistics(self):
        """测试获取统计"""
        engine = SimulationEngine(
            simulation_id="test-sim-007",
            agent_count=50,
            platforms=[Platform.WEIBO],
            duration="2h",
        )

        # 创建Agent后获取统计
        engine._create_agents()
        stats = engine.get_statistics()

        assert stats["simulation_id"] == "test-sim-007"
        assert stats["agent_count"] == 50
        assert "progress" in stats

    @pytest.mark.asyncio
    async def test_get_intermediate_result(self):
        """测试获取中间结果"""
        engine = SimulationEngine(
            simulation_id="test-sim-008",
            agent_count=30,
            duration="5h",
        )

        engine._create_agents()

        # 运行部分
        for _ in range(3):
            tick = engine.timeline.advance()
            if tick:
                actions = engine.simulator.simulate_tick(
                    agents_by_platform=engine.agents_by_platform,
                    current_hour=tick.hour,
                    seed_keywords=engine.seed_keywords,
                )
                all_actions = []
                for acts in actions.values():
                    all_actions.extend(acts)
                engine.report_generator.record_tick(tick, engine.agents, all_actions)

        intermediate = engine.get_intermediate_result()
        assert intermediate is not None

    @pytest.mark.asyncio
    async def test_keyword_extraction(self):
        """测试关键词提取"""
        engine = SimulationEngine(
            simulation_id="test-sim-009",
            seed_content="这是一条关于产品质量的新闻报道",
        )

        assert len(engine.seed_keywords) > 0

    @pytest.mark.asyncio
    async def test_reproducible_with_seed(self):
        """测试相同种子产生相同结果"""
        engine1 = SimulationEngine(
            simulation_id="test-sim-010a",
            agent_count=20,
            duration="2h",
            seed=12345,
        )

        engine2 = SimulationEngine(
            simulation_id="test-sim-010b",
            agent_count=20,
            duration="2h",
            seed=12345,
        )

        result1 = await engine1.run()
        result2 = await engine2.run()

        # 相同种子应该产生相似的立场分布
        assert abs(result1.sentiment_distribution["support"] -
                   result2.sentiment_distribution["support"]) < 0.1

    @pytest.mark.asyncio
    async def test_convenience_function(self):
        """测试便捷函数"""
        result = await run_simulation(
            simulation_id="test-sim-011",
            agent_count=30,
            duration="2h",
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_agent_distribution_across_platforms(self):
        """测试Agent在平台间的分配"""
        engine = SimulationEngine(
            simulation_id="test-sim-012",
            agent_count=100,
            platforms=[Platform.WEIBO, Platform.XIAOHONGSHU, Platform.DOUYIN],
            duration="2h",
        )

        engine._create_agents()

        # 每个平台应该有大致相等的Agent
        assert len(engine.agents_by_platform[Platform.WEIBO]) == 33
        assert len(engine.agents_by_platform[Platform.XIAOHONGSHU]) == 33
        assert len(engine.agents_by_platform[Platform.DOUYIN]) == 34  # 剩余分配给第一个平台

    @pytest.mark.asyncio
    async def test_progress_sequence(self):
        """测试进度序列的正确性"""
        engine = SimulationEngine(
            simulation_id="test-sim-013",
            agent_count=20,
            duration="5h",
        )

        ticks = []
        async for progress in engine.run_with_progress():
            if progress.status == "running":
                ticks.append(progress.tick)

        # tick应该是递增的
        assert ticks == sorted(ticks)

    @pytest.mark.asyncio
    async def test_pause_state(self):
        """测试暂停状态"""
        engine = SimulationEngine(
            simulation_id="test-sim-014",
            agent_count=10,
            duration="3h",
        )

        engine._create_agents()
        engine.pause()

        assert engine.is_paused == True

        engine.resume()
        assert engine.is_paused == False


class TestSimulationProgress:
    """模拟进度测试"""

    def test_progress_creation(self):
        """测试创建进度"""
        progress = SimulationProgress(
            simulation_id="test-001",
            tick=10,
            total_ticks=72,
            progress=0.14,
            current_hour=10,
            current_day=0,
            status="running",
            message="正在模拟",
        )

        assert progress.simulation_id == "test-001"
        assert progress.progress == 0.14

    def test_progress_values(self):
        """测试进度值"""
        progress = SimulationProgress(
            simulation_id="test-002",
            tick=36,
            total_ticks=72,
            progress=0.5,
            current_hour=12,
            current_day=1,
            status="running",
            message="Day 2, Hour 12",
        )

        assert progress.tick == 36
        assert progress.total_ticks == 72
        assert progress.current_day == 1
        assert progress.status == "running"
