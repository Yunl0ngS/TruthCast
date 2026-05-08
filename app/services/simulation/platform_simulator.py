"""平台模拟器 - 模拟不同社交媒体平台的交互机制"""

import random
from typing import Optional
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

from app.services.simulation.models import (
    Persona, AgentAction, Platform, RoleType, UserType
)
from app.services.simulation.action_engine import ActionEngine, ActionContext


@dataclass
class PlatformState:
    """平台状态"""

    platform: Platform

    # 当前时刻的内容列表
    active_contents: list[dict] = field(default_factory=list)

    # 热门话题
    trending_topics: list[str] = field(default_factory=list)

    # 统计数据
    total_posts: int = 0
    total_reposts: int = 0
    total_comments: int = 0
    total_likes: int = 0


class PlatformAdapter(ABC):
    """平台适配器基类"""

    platform: Platform

    @abstractmethod
    def get_action_weights(self, persona: Persona) -> dict[str, float]:
        """获取该平台下的行动权重"""
        pass

    @abstractmethod
    def calculate_reach(self, action: AgentAction, persona: Persona) -> int:
        """计算内容触达人数"""
        pass

    @abstractmethod
    def process_action(self, action: AgentAction, state: PlatformState) -> dict:
        """处理行动，返回效果"""
        pass


class WeiboAdapter(PlatformAdapter):
    """微博平台适配器"""

    platform = Platform.WEIBO

    # 微博内容分布
    CONTENT_DISTRIBUTION = {
        "text": 0.80,
        "image": 0.15,
        "video": 0.05,
    }

    def get_action_weights(self, persona: Persona) -> dict[str, float]:
        """微博行动权重"""
        weights = {
            "post": 0.15,
            "repost": 0.35,  # 转发是核心
            "comment": 0.20,
            "like": 0.25,
            "follow": 0.05,
        }

        # KOL在发帖权重更高
        if persona.role_type == RoleType.KOL:
            weights["post"] = 0.30
            weights["repost"] = 0.20

        # 核心用户发帖权重更高
        if persona.user_type == UserType.CORE:
            weights["post"] *= 1.5

        return weights

    def calculate_reach(self, action: AgentAction, persona: Persona) -> int:
        """
        计算微博触达人数

        微博是网状裂变传播
        """
        base_reach = persona.follower_count

        if action.action_type == "post":
            # 原帖触达 = 粉丝数 * 活跃度
            return int(base_reach * persona.activity)

        elif action.action_type == "repost":
            # 转发触达 = 粉丝数 * 影响力
            return int(base_reach * persona.influence)

        elif action.action_type == "comment":
            # 评论触达较低
            return int(base_reach * 0.1)

        else:
            return 0

    def process_action(self, action: AgentAction, state: PlatformState) -> dict:
        """处理微博行动"""
        effect = {
            "action_id": action.id,
            "action_type": action.action_type,
            "viral_potential": 0.0,
        }

        if action.action_type == "post":
            state.total_posts += 1
            # 微博帖子有上热搜潜力
            effect["viral_potential"] = 0.1
            state.active_contents.append({
                "id": action.id,
                "type": "post",
                "author_id": action.agent_id,
            })

        elif action.action_type == "repost":
            state.total_reposts += 1
            # 转发增加传播潜力
            effect["viral_potential"] = 0.2

        elif action.action_type == "comment":
            state.total_comments += 1

        elif action.action_type == "like":
            state.total_likes += 1

        return effect


class XiaohongshuAdapter(PlatformAdapter):
    """小红书平台适配器"""

    platform = Platform.XIAOHONGSHU

    # 小红书内容分布
    CONTENT_DISTRIBUTION = {
        "text": 0.0,
        "image": 0.70,
        "video": 0.30,
    }

    def get_action_weights(self, persona: Persona) -> dict[str, float]:
        """小红书行动权重"""
        weights = {
            "post": 0.25,      # 发布笔记
            "save": 0.35,      # 收藏（核心动作）
            "like": 0.20,
            "comment": 0.15,
            "follow": 0.05,
        }

        # 小红书用户更倾向收藏
        if persona.role_type == RoleType.NORMAL:
            weights["save"] = 0.40

        return weights

    def calculate_reach(self, action: AgentAction, persona: Persona) -> int:
        """
        小红书触达计算

        小红书是社区分发，收藏是核心指标
        """
        base_reach = persona.follower_count

        if action.action_type == "post":
            # 笔记触达 = 粉丝 + 算法推荐
            return int(base_reach * 1.5 + 1000)

        elif action.action_type == "save":
            # 收藏增加笔记权重
            return int(base_reach * 0.5)

        else:
            return int(base_reach * 0.1)

    def process_action(self, action: AgentAction, state: PlatformState) -> dict:
        """处理小红书行动"""
        effect = {
            "action_id": action.id,
            "action_type": action.action_type,
            "viral_potential": 0.0,
        }

        if action.action_type == "post":
            state.total_posts += 1
            effect["viral_potential"] = 0.15  # 小红书笔记有爆款潜力
            state.active_contents.append({
                "id": action.id,
                "type": "note",
                "author_id": action.agent_id,
            })

        elif action.action_type == "save":
            # 小红书收藏是核心认可指标
            state.total_likes += 1  # 归类到like统计
            effect["viral_potential"] = 0.3

        elif action.action_type == "like":
            state.total_likes += 1

        elif action.action_type == "comment":
            state.total_comments += 1

        return effect


class DouyinAdapter(PlatformAdapter):
    """抖音平台适配器"""

    platform = Platform.DOUYIN

    # 抖音内容分布
    CONTENT_DISTRIBUTION = {
        "text": 0.0,
        "image": 0.0,
        "video": 1.0,
    }

    def get_action_weights(self, persona: Persona) -> dict[str, float]:
        """抖音行动权重"""
        weights = {
            "post": 0.10,      # 上传视频
            "watch": 0.40,     # 观看（核心）
            "danmaku": 0.15,   # 弹幕
            "like": 0.25,
            "share": 0.10,
        }

        return weights

    def calculate_reach(self, action: AgentAction, persona: Persona) -> int:
        """
        抖音触达计算

        抖音是算法推荐，完播率是关键
        """
        if action.action_type == "post":
            # 视频触达完全由算法决定
            base = 500 + persona.follower_count
            return int(base * persona.influence * 2)

        elif action.action_type == "watch":
            # 观看行为增加推荐权重
            return 1

        else:
            return 0

    def process_action(self, action: AgentAction, state: PlatformState) -> dict:
        """处理抖音行动"""
        effect = {
            "action_id": action.id,
            "action_type": action.action_type,
            "viral_potential": 0.0,
        }

        if action.action_type == "post":
            state.total_posts += 1
            effect["viral_potential"] = 0.25  # 抖音爆款潜力最高
            state.active_contents.append({
                "id": action.id,
                "type": "video",
                "author_id": action.agent_id,
            })

        elif action.action_type == "danmaku":
            state.total_comments += 1

        elif action.action_type == "like":
            state.total_likes += 1

        return effect


class BilibiliAdapter(PlatformAdapter):
    """B站平台适配器"""

    platform = Platform.BILIBILI

    # B站内容分布
    CONTENT_DISTRIBUTION = {
        "text": 0.0,
        "image": 0.0,
        "video": 1.0,
    }

    def get_action_weights(self, persona: Persona) -> dict[str, float]:
        """B站行动权重"""
        weights = {
            "post": 0.15,      # 上传视频
            "danmaku": 0.30,   # 弹幕（核心）
            "triple": 0.20,    # 三连
            "comment": 0.25,
            "follow": 0.10,
        }

        # B站弹幕文化浓厚
        if persona.role_type in [RoleType.NORMAL, RoleType.NOVICE]:
            weights["danmaku"] = 0.40

        return weights

    def calculate_reach(self, action: AgentAction, persona: Persona) -> int:
        """
        B站触达计算

        B站是社区氛围，三连和弹幕是关键
        """
        base_reach = persona.follower_count

        if action.action_type == "post":
            return int(base_reach * 1.5 + 500)

        elif action.action_type == "triple":
            # 三连大幅提升推荐
            return int(base_reach * 0.3)

        elif action.action_type == "danmaku":
            # 弹幕增加视频热度
            return 1

        else:
            return 0

    def process_action(self, action: AgentAction, state: PlatformState) -> dict:
        """处理B站行动"""
        effect = {
            "action_id": action.id,
            "action_type": action.action_type,
            "viral_potential": 0.0,
        }

        if action.action_type == "post":
            state.total_posts += 1
            effect["viral_potential"] = 0.2
            state.active_contents.append({
                "id": action.id,
                "type": "video",
                "author_id": action.agent_id,
            })

        elif action.action_type == "triple":
            # 三连 = 点赞 + 投币 + 收藏
            state.total_likes += 3
            effect["viral_potential"] = 0.4

        elif action.action_type == "danmaku":
            state.total_comments += 1

        elif action.action_type == "comment":
            state.total_comments += 1

        return effect


# 平台适配器注册表
PLATFORM_ADAPTERS: dict[Platform, type[PlatformAdapter]] = {
    Platform.WEIBO: WeiboAdapter,
    Platform.XIAOHONGSHU: XiaohongshuAdapter,
    Platform.DOUYIN: DouyinAdapter,
    Platform.BILIBILI: BilibiliAdapter,
}


class PlatformSimulator:
    """平台模拟器"""

    def __init__(self, platform: Platform, seed: Optional[int] = None):
        """
        初始化模拟器

        Args:
            platform: 平台类型
            seed: 随机种子
        """
        self.platform = platform
        self.adapter = self._get_adapter(platform)
        self.state = PlatformState(platform=platform)
        self.rng = random.Random(seed)
        self.action_engine = ActionEngine(seed=seed)

    def _get_adapter(self, platform: Platform) -> PlatformAdapter:
        """获取平台适配器"""
        adapter_class = PLATFORM_ADAPTERS.get(platform)
        if not adapter_class:
            raise ValueError(f"Unsupported platform: {platform}")
        return adapter_class()

    def simulate_tick(
        self,
        agents: list[Persona],
        current_hour: int,
        seed_keywords: list[str],
    ) -> list[AgentAction]:
        """
        模拟一个时间刻度

        Args:
            agents: Agent列表
            current_hour: 当前小时
            seed_keywords: 种子关键词

        Returns:
            该时刻产生的行动列表
        """
        context = ActionContext(
            current_hour=current_hour,
            seed_keywords=seed_keywords,
            trending_topics=self.state.trending_topics,
            seen_content_ids=[],
            interacted_user_ids=[],
        )

        actions = []

        for agent in agents:
            # 判断是否行动
            action = self.action_engine.decide(agent, context)

            if action:
                # 使用平台特定权重重新校准行动类型
                platform_weights = self.adapter.get_action_weights(agent)
                if action.action_type in platform_weights:
                    # 有一定概率改变行动类型以符合平台特征
                    if self.rng.random() < 0.3:
                        action_types = list(platform_weights.keys())
                        weights = list(platform_weights.values())
                        action.action_type = self.rng.choices(
                            action_types, weights=weights
                        )[0]

                # 处理行动
                effect = self.adapter.process_action(action, self.state)

                actions.append(action)

        return actions

    def get_statistics(self) -> dict:
        """获取平台统计数据"""
        return {
            "platform": self.platform.value,
            "total_posts": self.state.total_posts,
            "total_reposts": self.state.total_reposts,
            "total_comments": self.state.total_comments,
            "total_likes": self.state.total_likes,
            "active_contents": len(self.state.active_contents),
        }


class MultiPlatformSimulator:
    """多平台并行模拟器"""

    def __init__(
        self,
        platforms: list[Platform],
        seed: Optional[int] = None
    ):
        """
        初始化多平台模拟器

        Args:
            platforms: 平台列表
            seed: 随机种子
        """
        self.simulators = {
            p: PlatformSimulator(p, seed=seed) for p in platforms
        }

    def simulate_tick(
        self,
        agents_by_platform: dict[Platform, list[Persona]],
        current_hour: int,
        seed_keywords: list[str],
    ) -> dict[Platform, list[AgentAction]]:
        """
        多平台并行模拟一个时间刻度

        Args:
            agents_by_platform: 按平台分组的Agent
            current_hour: 当前小时
            seed_keywords: 种子关键词

        Returns:
            各平台的行动列表
        """
        results = {}

        for platform, simulator in self.simulators.items():
            agents = agents_by_platform.get(platform, [])
            if agents:
                actions = simulator.simulate_tick(
                    agents=agents,
                    current_hour=current_hour,
                    seed_keywords=seed_keywords,
                )
                results[platform] = actions

        return results

    def get_all_statistics(self) -> dict:
        """获取所有平台统计"""
        return {
            p.value: s.get_statistics()
            for p, s in self.simulators.items()
        }
