"""行动决策引擎 - 决定Agent的行动"""

import random
import uuid
from typing import Optional
from dataclasses import dataclass

from app.services.simulation.models import (
    Persona, AgentAction, Platform, RoleType, Stance
)


@dataclass
class ActionContext:
    """行动上下文"""

    # 当前模拟时间（小时，0-23）
    current_hour: int

    # 种子材料关键词
    seed_keywords: list[str]

    # 当前热门话题（简化版，实际可能是更复杂的结构）
    trending_topics: list[str]

    # Agent已看到的内容ID列表
    seen_content_ids: list[str]

    # Agent已交互的用户ID列表
    interacted_user_ids: list[str]


class ActionEngine:
    """行动决策引擎"""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def _get_activity_modifier(self, persona: Persona, current_hour: int) -> float:
        """
        获取当前时刻的活跃度修正值

        基于24小时时间模式
        """
        base_activity = persona.activity
        temporal_prob = persona.temporal_pattern.pattern[current_hour]

        # 综合活跃度 = 基础活跃度 * 时间模式
        return base_activity * temporal_prob

    def _should_act(self, persona: Persona, current_hour: int) -> bool:
        """
        判断Agent是否应该行动

        基于活跃度和时间模式
        """
        activity_modifier = self._get_activity_modifier(persona, current_hour)

        # 基础行动概率
        base_prob = 0.1

        # 高活跃度角色行动概率更高
        if persona.role_type in [RoleType.KOL, RoleType.EXTREME, RoleType.TROLL]:
            base_prob = 0.2
        elif persona.role_type in [RoleType.OFFICIAL, RoleType.BYSTANDER]:
            base_prob = 0.05

        # 最终概率 = 基础概率 * 活跃度修正
        final_prob = base_prob * (0.5 + activity_modifier)

        return self.rng.random() < final_prob

    def _decide_action_type(
        self,
        persona: Persona,
        context: ActionContext
    ) -> str:
        """
        决定行动类型

        基于人格参数和上下文
        """
        # 各行动类型的权重
        weights = {
            "post": 0.2,
            "repost": 0.3,
            "comment": 0.2,
            "like": 0.2,
            "follow": 0.1,
        }

        # 根据角色类型调整权重
        if persona.role_type == RoleType.KOL:
            # KOL更倾向发帖
            weights["post"] = 0.4
            weights["repost"] = 0.2
        elif persona.role_type == RoleType.NORMAL:
            # 普通网友更倾向转发和点赞
            weights["repost"] = 0.4
            weights["like"] = 0.3
        elif persona.role_type == RoleType.RATIONAL:
            # 理性派更倾向评论
            weights["comment"] = 0.4
            weights["post"] = 0.3
        elif persona.role_type == RoleType.EXTREME:
            # 极端粉丝活跃发帖和评论
            weights["post"] = 0.35
            weights["comment"] = 0.35
        elif persona.role_type == RoleType.BYSTANDER:
            # 吃瓜群众主要点赞和转发
            weights["like"] = 0.4
            weights["repost"] = 0.3
        elif persona.role_type == RoleType.OFFICIAL:
            # 官方号主要发帖
            weights["post"] = 0.6
            weights["comment"] = 0.2
        elif persona.role_type == RoleType.TROLL:
            # 职业喷活跃评论
            weights["comment"] = 0.5
            weights["post"] = 0.2
        elif persona.role_type == RoleType.NOVICE:
            # 萌新主要围观
            weights["like"] = 0.5
            weights["follow"] = 0.2

        # 根据Big Five微调
        big_five = persona.big_five

        # 高外向性更倾向发帖和评论
        if big_five.extraversion > 0.7:
            weights["post"] *= 1.3
            weights["comment"] *= 1.3

        # 高宜人性更倾向点赞
        if big_five.agreeableness > 0.7:
            weights["like"] *= 1.5

        # 高神经质更倾向评论
        if big_five.neuroticism > 0.7:
            weights["comment"] *= 1.3

        # 高从众度更倾向转发
        if persona.conformity > 0.7:
            weights["repost"] *= 1.5

        # 归一化权重
        total = sum(weights.values())
        normalized = {k: v / total for k, v in weights.items()}

        # 选择行动类型
        actions = list(normalized.keys())
        probs = list(normalized.values())
        return self.rng.choices(actions, weights=probs)[0]

    def _generate_content(
        self,
        persona: Persona,
        action_type: str,
        context: ActionContext
    ) -> str:
        """
        生成行动内容

        注意：这是简化版，实际应该调用LLM
        """
        # 获取种子关键词
        keywords = context.seed_keywords[:3] if context.seed_keywords else ["话题"]

        # 根据立场和角色生成内容
        stance = persona.stance

        if action_type == "post":
            if stance == Stance.SUPPORT:
                templates = [
                    f"支持！关于{keywords[0]}，我觉得做得不错。",
                    f"这个{keywords[0]}真的很好，推荐！",
                    f"终于等到{keywords[0]}的消息了，期待！",
                ]
            elif stance == Stance.OPPOSE:
                templates = [
                    f"不太认同{keywords[0]}的说法...",
                    f"这个{keywords[0]}有问题吧？",
                    f"关于{keywords[0]}，我有不同看法。",
                ]
            else:
                templates = [
                    f"关于{keywords[0]}，大家怎么看？",
                    f"今天看到{keywords[0]}的消息，来聊聊。",
                    f"刚看到{keywords[0]}，观望中...",
                ]
        elif action_type == "repost":
            templates = [
                f"转发关于{keywords[0]}的内容",
                f"mark一下{keywords[0]}",
                f"这个{keywords[0]}值得关注",
            ]
        elif action_type == "comment":
            if stance == Stance.SUPPORT:
                templates = ["说得好！", "支持！", "有道理~"]
            elif stance == Stance.OPPOSE:
                templates = ["不太同意...", "这观点有问题吧", "emmm..."]
            else:
                templates = ["学习了", "了解", "mark"]
        else:
            templates = [""]  # like/follow不需要内容

        return self.rng.choice(templates)

    def decide(
        self,
        persona: Persona,
        context: ActionContext
    ) -> Optional[AgentAction]:
        """
        决定Agent的行动

        Args:
            persona: Agent人格
            context: 行动上下文

        Returns:
            AgentAction实例，如果决定不行动则返回None
        """
        # 判断是否行动
        if not self._should_act(persona, context.current_hour):
            return None

        # 决定行动类型
        action_type = self._decide_action_type(persona, context)

        # 生成内容
        content = self._generate_content(persona, action_type, context)

        # 创建行动记录
        action = AgentAction(
            id=f"action-{uuid.uuid4().hex[:12]}",
            agent_id=persona.id,
            action_type=action_type,
            content=content,
            platform=persona.platform,
        )

        return action

    def decide_batch(
        self,
        personas: list[Persona],
        context: ActionContext
    ) -> list[AgentAction]:
        """
        批量决定行动

        Args:
            personas: Agent列表
            context: 行动上下文

        Returns:
            行动列表（可能少于Agent数量）
        """
        actions = []
        for persona in personas:
            action = self.decide(persona, context)
            if action:
                actions.append(action)
        return actions
