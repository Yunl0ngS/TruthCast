"""报告生成器测试"""

import pytest
from app.services.simulation.report_generator import ReportGenerator, StanceSnapshot
from app.services.simulation.models import (
    Persona, AgentAction, Stance, RoleType, Platform
)
from app.services.simulation.timeline import Timeline, SimulationTick
from app.services.simulation.persona_factory import PersonaFactory


@pytest.fixture
def sample_agents():
    """创建测试Agent"""
    factory = PersonaFactory(seed=42)
    return factory.create_batch(count=20, platform=Platform.WEIBO)


@pytest.fixture
def sample_tick():
    """创建测试刻度"""
    return SimulationTick(
        tick=0,
        hour=10,
        day=0,
        datetime_sim=None,
    )


class TestReportGenerator:
    """报告生成器测试"""

    def test_initialization(self):
        """测试初始化"""
        generator = ReportGenerator()
        assert len(generator.stance_history) == 0
        assert len(generator.viral_contents) == 0

    def test_record_tick(self, sample_agents, sample_tick):
        """测试记录刻度"""
        generator = ReportGenerator()

        actions = []
        generator.record_tick(sample_tick, sample_agents, actions)

        assert len(generator.stance_history) == 1

        snapshot = generator.stance_history[0]
        assert snapshot.tick == 0
        assert 0 <= snapshot.support <= 1
        assert 0 <= snapshot.oppose <= 1

    def test_record_tick_with_actions(self, sample_agents, sample_tick):
        """测试记录带行动的刻度"""
        generator = ReportGenerator()

        # 创建一些行动
        actions = [
            AgentAction(
                id="action-1",
                agent_id=sample_agents[0].id,
                action_type="post",
                content="测试内容",
                platform=Platform.WEIBO,
            ),
            AgentAction(
                id="action-2",
                agent_id=sample_agents[1].id,
                action_type="comment",
                content="测试评论",
                platform=Platform.WEIBO,
            ),
        ]

        generator.record_tick(sample_tick, sample_agents, actions)

        assert len(generator.action_history) == 2

    def test_generate_result(self, sample_agents):
        """测试生成结果"""
        generator = ReportGenerator()

        # 模拟多个时刻
        for i in range(5):
            tick = SimulationTick(tick=i, hour=i, day=0, datetime_sim=None)
            actions = []
            generator.record_tick(tick, sample_agents, actions)

        result = generator.generate_result()

        assert result.sentiment_distribution is not None
        assert "support" in result.sentiment_distribution
        assert isinstance(result.opinion_clusters, list)
        assert isinstance(result.trigger_points, list)
        assert isinstance(result.risk_warnings, list)
        assert isinstance(result.suggestions, list)

    def test_stance_distribution_calculation(self):
        """测试立场分布计算"""
        generator = ReportGenerator()

        # 创建特定立场的Agent
        agents = []
        for i in range(10):
            agent = PersonaFactory(seed=i).create_persona()
            if i < 4:
                agent.stance = Stance.SUPPORT
            elif i < 7:
                agent.stance = Stance.OPPOSE
            else:
                agent.stance = Stance.NEUTRAL
            agents.append(agent)

        tick = SimulationTick(tick=0, hour=0, day=0, datetime_sim=None)
        generator.record_tick(tick, agents, [])

        snapshot = generator.stance_history[0]

        assert abs(snapshot.support - 0.4) < 0.01  # 4/10
        assert abs(snapshot.oppose - 0.3) < 0.01   # 3/10
        assert abs(snapshot.neutral - 0.3) < 0.01  # 3/10

    def test_viral_content_detection(self):
        """测试爆款内容检测"""
        generator = ReportGenerator()
        factory = PersonaFactory(seed=42)

        # 创建高影响力KOL
        kol = factory.create_persona(role_type=RoleType.KOL)

        tick = SimulationTick(tick=0, hour=0, day=0, datetime_sim=None)

        # KOL发帖
        action = AgentAction(
            id="action-kol",
            agent_id=kol.id,
            action_type="post",
            content="重要内容",
            platform=Platform.WEIBO,
        )

        generator.record_tick(tick, [kol], [action])

        # KOL发帖应该被识别为爆款
        assert len(generator.viral_contents) >= 1

    def test_risk_warnings_generation(self):
        """测试风险预警生成"""
        generator = ReportGenerator()

        # 创建高反对比例的快照
        for i in range(10):
            snapshot = StanceSnapshot(
                tick=i,
                support=0.2,
                oppose=0.5,  # 高反对
                neutral=0.2,
                fickle=0.1,
            )
            generator.stance_history.append(snapshot)

        result = generator.generate_result()

        # 应该有反对比例过高的预警
        assert len(result.risk_warnings) > 0
        assert any("反对" in w for w in result.risk_warnings)

    def test_suggestions_generation(self):
        """测试建议生成"""
        generator = ReportGenerator()

        # 创建立场快照
        for i in range(10):
            snapshot = StanceSnapshot(
                tick=i,
                support=0.3,
                oppose=0.3,
                neutral=0.3,
                fickle=0.1,
            )
            generator.stance_history.append(snapshot)

        result = generator.generate_result()

        assert len(result.suggestions) > 0

    def test_opinion_clusters(self):
        """测试观点聚类"""
        generator = ReportGenerator()

        snapshot = StanceSnapshot(
            tick=0,
            support=0.3,
            oppose=0.4,
            neutral=0.3,
            fickle=0.0,
        )
        generator.stance_history.append(snapshot)

        result = generator.generate_result()

        # 应该有三个聚类
        assert len(result.opinion_clusters) >= 2

        # 每个聚类应该有立场和比例
        for cluster in result.opinion_clusters:
            assert "stance" in cluster
            assert "ratio" in cluster

    def test_get_stance_trend(self):
        """测试获取立场趋势"""
        generator = ReportGenerator()

        for i in range(5):
            snapshot = StanceSnapshot(
                tick=i,
                support=0.3 + i * 0.05,
                oppose=0.3 - i * 0.03,
                neutral=0.3,
                fickle=0.1,
            )
            generator.stance_history.append(snapshot)

        trend = generator.get_stance_trend()

        assert len(trend) == 5
        assert trend[0]["tick"] == 0
        assert trend[4]["support"] > trend[0]["support"]

    def test_trigger_points_identification(self):
        """测试引爆点识别"""
        generator = ReportGenerator()

        # 模拟立场突变
        for i in range(10):
            snapshot = StanceSnapshot(
                tick=i,
                support=0.3 if i < 5 else 0.5,  # 第5个时刻突变
                oppose=0.4 if i < 5 else 0.2,
                neutral=0.2,
                fickle=0.1,
            )
            generator.stance_history.append(snapshot)

        result = generator.generate_result()

        # 应该检测到立场变化
        stance_shifts = [t for t in result.trigger_points if t["type"] == "stance_shift"]
        assert len(stance_shifts) > 0

    def test_graph_data_generation(self):
        """测试图数据生成"""
        generator = ReportGenerator()
        factory = PersonaFactory(seed=42)

        agents = factory.create_batch(count=5, platform=Platform.WEIBO)

        # 创建行动
        actions = [
            AgentAction(
                id=f"action-{i}",
                agent_id=agents[i].id,
                action_type="post",
                content=f"内容{i}",
                platform=Platform.WEIBO,
            )
            for i in range(5)
        ]

        tick = SimulationTick(tick=0, hour=0, day=0, datetime_sim=None)
        generator.record_tick(tick, agents, actions)

        nodes, edges = generator._generate_graph_data()

        assert len(nodes) == 5
        for node in nodes:
            assert "id" in node
            assert "action_count" in node


class TestStanceSnapshot:
    """立场快照测试"""

    def test_snapshot_creation(self):
        """测试快照创建"""
        snapshot = StanceSnapshot(
            tick=10,
            support=0.4,
            oppose=0.3,
            neutral=0.2,
            fickle=0.1,
        )

        assert snapshot.tick == 10
        assert snapshot.support == 0.4
        assert snapshot.oppose == 0.3
        assert abs((snapshot.support + snapshot.oppose + snapshot.neutral + snapshot.fickle) - 1.0) < 0.01
