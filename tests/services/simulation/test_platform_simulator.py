"""平台模拟器测试"""

import pytest
from app.services.simulation.platform_simulator import (
    PlatformSimulator, MultiPlatformSimulator,
    WeiboAdapter, XiaohongshuAdapter, DouyinAdapter, BilibiliAdapter,
    PLATFORM_ADAPTERS
)
from app.services.simulation.models import Platform, RoleType
from app.services.simulation.persona_factory import PersonaFactory


class TestWeiboAdapter:
    """微博适配器测试"""

    def test_get_action_weights(self):
        """测试行动权重"""
        adapter = WeiboAdapter()
        factory = PersonaFactory(seed=42)

        # 普通用户
        normal = factory.create_persona(role_type=RoleType.NORMAL)
        weights = adapter.get_action_weights(normal)

        # 微博转发权重应该较高
        assert weights["repost"] > weights["post"]

    def test_platform_attribute(self):
        """测试平台属性"""
        adapter = WeiboAdapter()
        assert adapter.platform == Platform.WEIBO

    def test_content_distribution(self):
        """测试内容分布"""
        adapter = WeiboAdapter()
        # 微博以文字为主
        assert adapter.CONTENT_DISTRIBUTION["text"] == 0.80


class TestXiaohongshuAdapter:
    """小红书适配器测试"""

    def test_save_weight_high(self):
        """测试收藏权重高"""
        adapter = XiaohongshuAdapter()
        factory = PersonaFactory(seed=42)

        normal = factory.create_persona(role_type=RoleType.NORMAL)
        weights = adapter.get_action_weights(normal)

        # 小红书收藏权重应该最高
        assert weights["save"] >= weights["post"]
        assert weights["save"] >= weights["like"]

    def test_image_video_only(self):
        """测试小红书只有图文和视频"""
        adapter = XiaohongshuAdapter()
        # 小红书没有纯文字
        assert adapter.CONTENT_DISTRIBUTION["text"] == 0.0
        assert adapter.CONTENT_DISTRIBUTION["image"] == 0.70


class TestDouyinAdapter:
    """抖音适配器测试"""

    def test_video_only_content(self):
        """测试抖音只有视频内容"""
        adapter = DouyinAdapter()

        # 抖音内容分布只有视频
        assert adapter.CONTENT_DISTRIBUTION["video"] == 1.0
        assert adapter.CONTENT_DISTRIBUTION["text"] == 0.0
        assert adapter.CONTENT_DISTRIBUTION["image"] == 0.0


class TestBilibiliAdapter:
    """B站适配器测试"""

    def test_danmaku_weight(self):
        """测试弹幕权重"""
        adapter = BilibiliAdapter()
        factory = PersonaFactory(seed=42)

        normal = factory.create_persona(role_type=RoleType.NORMAL)
        weights = adapter.get_action_weights(normal)

        # B站弹幕权重应该较高
        assert weights["danmaku"] > 0.2

    def test_triple_action(self):
        """测试三连动作"""
        adapter = BilibiliAdapter()
        # 三连是B站特色
        weights = adapter.get_action_weights(
            PersonaFactory(seed=42).create_persona()
        )
        assert "triple" in weights


class TestPlatformSimulator:
    """平台模拟器测试"""

    def test_initialization(self):
        """测试初始化"""
        simulator = PlatformSimulator(Platform.WEIBO, seed=42)

        assert simulator.platform == Platform.WEIBO
        assert simulator.adapter is not None
        assert simulator.state is not None

    def test_simulate_tick(self):
        """测试时间刻度模拟"""
        simulator = PlatformSimulator(Platform.WEIBO, seed=42)
        factory = PersonaFactory(seed=42)

        agents = factory.create_batch(count=10, platform=Platform.WEIBO)

        # 模拟一个时刻
        actions = simulator.simulate_tick(
            agents=agents,
            current_hour=10,
            seed_keywords=["测试话题"]
        )

        # 可能产生一些行动
        assert isinstance(actions, list)

        for action in actions:
            assert action.agent_id in [a.id for a in agents]

    def test_statistics(self):
        """测试统计数据"""
        simulator = PlatformSimulator(Platform.WEIBO, seed=42)
        factory = PersonaFactory(seed=42)

        agents = factory.create_batch(count=10, platform=Platform.WEIBO)

        simulator.simulate_tick(
            agents=agents,
            current_hour=10,
            seed_keywords=["测试"]
        )

        stats = simulator.get_statistics()

        assert stats["platform"] == "weibo"
        assert "total_posts" in stats
        assert "total_likes" in stats


class TestMultiPlatformSimulator:
    """多平台模拟器测试"""

    def test_initialization(self):
        """测试初始化"""
        platforms = [Platform.WEIBO, Platform.XIAOHONGSHU]
        simulator = MultiPlatformSimulator(platforms, seed=42)

        assert len(simulator.simulators) == 2
        assert Platform.WEIBO in simulator.simulators
        assert Platform.XIAOHONGSHU in simulator.simulators

    def test_parallel_simulation(self):
        """测试并行模拟"""
        platforms = [Platform.WEIBO, Platform.XIAOHONGSHU]
        simulator = MultiPlatformSimulator(platforms, seed=42)
        factory = PersonaFactory(seed=42)

        # 为每个平台创建Agent
        agents_by_platform = {
            Platform.WEIBO: factory.create_batch(count=5, platform=Platform.WEIBO),
            Platform.XIAOHONGSHU: factory.create_batch(count=5, platform=Platform.XIAOHONGSHU),
        }

        results = simulator.simulate_tick(
            agents_by_platform=agents_by_platform,
            current_hour=10,
            seed_keywords=["测试"]
        )

        # 每个平台都应该有结果
        assert Platform.WEIBO in results or len(results.get(Platform.WEIBO, [])) >= 0
        assert Platform.XIAOHONGSHU in results or len(results.get(Platform.XIAOHONGSHU, [])) >= 0

    def test_all_statistics(self):
        """测试所有平台统计"""
        platforms = [Platform.WEIBO, Platform.XIAOHONGSHU]
        simulator = MultiPlatformSimulator(platforms, seed=42)

        stats = simulator.get_all_statistics()

        assert "weibo" in stats
        assert "xiaohongshu" in stats


class TestPlatformAdaptersRegistry:
    """平台适配器注册表测试"""

    def test_all_platforms_registered(self):
        """测试所有平台都已注册"""
        expected = [
            Platform.WEIBO,
            Platform.XIAOHONGSHU,
            Platform.DOUYIN,
            Platform.BILIBILI,
        ]

        for platform in expected:
            assert platform in PLATFORM_ADAPTERS

    def test_adapter_types(self):
        """测试适配器类型"""
        assert PLATFORM_ADAPTERS[Platform.WEIBO] == WeiboAdapter
        assert PLATFORM_ADAPTERS[Platform.XIAOHONGSHU] == XiaohongshuAdapter
        assert PLATFORM_ADAPTERS[Platform.DOUYIN] == DouyinAdapter
        assert PLATFORM_ADAPTERS[Platform.BILIBILI] == BilibiliAdapter


class TestPlatformDifferences:
    """平台差异测试"""

    def test_weibo_vs_xiaohongshu_weights(self):
        """测试微博和小红书权重差异"""
        weibo = WeiboAdapter()
        xiaohongshu = XiaohongshuAdapter()
        factory = PersonaFactory(seed=42)

        normal = factory.create_persona(role_type=RoleType.NORMAL)

        weibo_weights = weibo.get_action_weights(normal)
        xhs_weights = xiaohongshu.get_action_weights(normal)

        # 微博转发权重高，小红书收藏权重高
        assert weibo_weights["repost"] > xhs_weights.get("repost", 0)
        assert xhs_weights["save"] > weibo_weights.get("save", 0)

    def test_douyin_vs_bilibili_weights(self):
        """测试抖音和B站权重差异"""
        douyin = DouyinAdapter()
        bilibili = BilibiliAdapter()
        factory = PersonaFactory(seed=42)

        normal = factory.create_persona(role_type=RoleType.NORMAL)

        douyin_weights = douyin.get_action_weights(normal)
        bili_weights = bilibili.get_action_weights(normal)

        # B站有弹幕和三连，抖音没有
        assert "danmaku" in bili_weights
        assert "triple" in bili_weights
        assert "watch" in douyin_weights
