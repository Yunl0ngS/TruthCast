"""Agent人格工厂 - 批量生成Agent实例"""

import random
import uuid
from typing import Optional
from app.services.simulation.models import (
    Persona, BigFive, TemporalPattern, RoleType, Stance,
    UserType, Platform
)
from app.services.simulation.persona_templates import (
    ROLE_CONFIGS, PROFESSION_CATEGORIES,
    FIRST_NAMES_MALE, FIRST_NAMES_FEMALE, LAST_NAMES,
    USERNAME_PREFIXES, BIO_TEMPLATES, RoleConfig
)


class PersonaFactory:
    """Agent人格工厂"""

    def __init__(
        self,
        seed: Optional[int] = None,
        core_user_ratio: float = 0.15
    ):
        """
        初始化工厂

        Args:
            seed: 随机种子，用于可复现
            core_user_ratio: 核心用户占比，默认15%
        """
        self.rng = random.Random(seed)
        self.core_user_ratio = core_user_ratio

    def _random_in_range(self, range_tuple: tuple[float, float]) -> float:
        """在范围内生成随机值"""
        return self.rng.uniform(range_tuple[0], range_tuple[1])

    def _generate_name(self) -> tuple[str, str]:
        """生成姓名和用户名"""
        last_name = self.rng.choice(LAST_NAMES)
        is_male = self.rng.random() < 0.5

        if is_male:
            first_name = self.rng.choice(FIRST_NAMES_MALE)
        else:
            first_name = self.rng.choice(FIRST_NAMES_FEMALE)

        name = f"{last_name}{first_name}"

        # 生成用户名
        prefix = self.rng.choice(USERNAME_PREFIXES)
        suffix = self.rng.randint(100, 9999)
        username = f"{prefix}{suffix}"

        return name, username

    def _generate_big_five(self, config: RoleConfig) -> BigFive:
        """生成Big Five人格"""
        return BigFive(
            openness=self._random_in_range(config.openness_range),
            conscientiousness=self._random_in_range(config.conscientiousness_range),
            extraversion=self._random_in_range(config.extraversion_range),
            agreeableness=self._random_in_range(config.agreeableness_range),
            neuroticism=self._random_in_range(config.neuroticism_range),
        )

    def _generate_temporal_pattern(self) -> TemporalPattern:
        """生成时间活跃模式"""
        # 三种模式：早起型、工作型、夜猫型
        pattern_type = self.rng.choices(
            ["early_bird", "workday", "night_owl"],
            weights=[0.2, 0.5, 0.3]
        )[0]

        if pattern_type == "early_bird":
            return self._create_early_bird_pattern()
        elif pattern_type == "workday":
            return TemporalPattern.create_workday()
        else:
            return TemporalPattern.create_night_owl()

    def _create_early_bird_pattern(self) -> TemporalPattern:
        """早起型模式"""
        pattern = [0.0] * 24
        # 5-8点活跃
        for i in range(5, 8):
            pattern[i] = 0.5 + (i - 5) * 0.1
        # 12-14点午休活跃
        for i in range(12, 14):
            pattern[i] = 0.4
        # 18-21点晚间
        for i in range(18, 21):
            pattern[i] = 0.3
        return TemporalPattern(pattern=pattern)

    def _generate_profession(self) -> tuple[str, str]:
        """生成职业"""
        # 按权重选择类别
        category = self.rng.choices(
            PROFESSION_CATEGORIES,
            weights=[c.ratio for c in PROFESSION_CATEGORIES]
        )[0]

        profession = self.rng.choice(category.professions)
        return profession, category.category

    def _generate_bio(self, role_type: RoleType) -> str:
        """生成Bio"""
        templates = BIO_TEMPLATES.get(role_type, ["普通用户"])

        # 特殊处理 KOL 和 EXTREME
        if role_type == RoleType.KOL:
            topics = ["科技", "数码", "汽车", "美食", "旅游", "时尚", "财经"]
            template = self.rng.choice(templates)
            return template.format(topic=self.rng.choice(topics))
        elif role_type == RoleType.EXTREME:
            targets = ["某品牌", "某明星", "某产品", "某公司"]
            template = self.rng.choice(templates)
            return template.format(target=self.rng.choice(targets))

        return self.rng.choice(templates)

    def _determine_user_type(
        self,
        config: RoleConfig,
        influence: float
    ) -> UserType:
        """确定用户类型（核心/普通）"""
        # KOL 和 Official 强制为核心用户
        if config.role_type in [RoleType.KOL, RoleType.OFFICIAL]:
            return UserType.CORE

        # 其他角色按比例确定
        if self.rng.random() < self.core_user_ratio:
            return UserType.CORE

        # 高影响力也可能成为核心用户
        if influence >= 0.7:
            return UserType.CORE

        return UserType.ORDINARY

    def _generate_follower_count(self, user_type: UserType, role_type: RoleType) -> int:
        """生成粉丝数"""
        if user_type == UserType.CORE:
            if role_type == RoleType.KOL:
                return self.rng.randint(10000, 1000000)
            elif role_type == RoleType.OFFICIAL:
                return self.rng.randint(50000, 5000000)
            else:
                return self.rng.randint(10000, 100000)
        else:
            return self.rng.randint(0, 10000)

    def create_persona(
        self,
        platform: Platform = Platform.WEIBO,
        role_type: Optional[RoleType] = None,
        stance: Optional[Stance] = None,
    ) -> Persona:
        """
        创建单个Agent人格

        Args:
            platform: 所属平台
            role_type: 指定角色类型，不指定则随机
            stance: 指定立场，不指定则根据角色默认

        Returns:
            Persona实例
        """
        # 选择角色类型
        if role_type is None:
            role_types = list(ROLE_CONFIGS.keys())
            weights = [ROLE_CONFIGS[rt].ratio for rt in role_types]
            role_type = self.rng.choices(role_types, weights=weights)[0]

        config = ROLE_CONFIGS[role_type]

        # 生成基础信息
        name, username = self._generate_name()
        profession, profession_category = self._generate_profession()

        # 生成人格参数
        big_five = self._generate_big_five(config)
        temporal_pattern = self._generate_temporal_pattern()

        # 生成行为参数
        influence = self._random_in_range(config.influence_range)
        activity = self._random_in_range(config.activity_range)
        conformity = self._random_in_range(config.conformity_range)
        expertise = self._random_in_range(config.expertise_range)
        stance_flexibility = self._random_in_range(config.stance_flexibility_range)

        # 确定用户类型和粉丝数
        user_type = self._determine_user_type(config, influence)
        follower_count = self._generate_follower_count(user_type, role_type)

        # 确定立场
        if stance is None:
            stance = config.default_stance

        # 选择发言风格
        language_style = self.rng.choice(config.language_styles)

        return Persona(
            id=f"agent-{uuid.uuid4().hex[:12]}",
            name=name,
            username=username,
            bio=self._generate_bio(role_type),
            role_type=role_type,
            platform=platform,
            big_five=big_five,
            stance=stance,
            stance_flexibility=stance_flexibility,
            influence=influence,
            activity=activity,
            conformity=conformity,
            expertise=expertise,
            temporal_pattern=temporal_pattern,
            user_type=user_type,
            follower_count=follower_count,
            profession=profession,
            profession_category=profession_category,
            language_style=language_style,
        )

    def create_batch(
        self,
        count: int,
        platform: Platform = Platform.WEIBO,
        role_distribution: Optional[dict[RoleType, int]] = None,
        stance_distribution: Optional[dict[Stance, float]] = None,
    ) -> list[Persona]:
        """
        批量创建Agent人格

        Args:
            count: Agent数量
            platform: 所属平台
            role_distribution: 指定各角色类型的数量，不指定则按默认比例
            stance_distribution: 指定立场分布概率，如 {SUPPORT: 0.3, OPPOSE: 0.2, NEUTRAL: 0.5}

        Returns:
            Persona列表
        """
        personas = []

        if role_distribution is None:
            # 按默认比例分配
            role_distribution = {}
            remaining = count
            for role_type, config in ROLE_CONFIGS.items():
                role_count = int(count * config.ratio)
                role_distribution[role_type] = role_count
                remaining -= role_count
            # 将剩余分配给 NORMAL
            if remaining > 0:
                role_distribution[RoleType.NORMAL] += remaining

        for role_type, role_count in role_distribution.items():
            for _ in range(role_count):
                # 确定立场
                stance = None
                if stance_distribution:
                    stances = list(stance_distribution.keys())
                    weights = list(stance_distribution.values())
                    stance = self.rng.choices(stances, weights=weights)[0]

                persona = self.create_persona(
                    platform=platform,
                    role_type=role_type,
                    stance=stance,
                )
                personas.append(persona)

        # 打乱顺序
        self.rng.shuffle(personas)
        return personas


def create_agent_pool(
    count: int = 500,
    platform: Platform = Platform.WEIBO,
    seed: Optional[int] = None,
    stance_distribution: Optional[dict[Stance, float]] = None,
) -> list[Persona]:
    """
    创建Agent池的便捷函数

    Args:
        count: Agent数量
        platform: 平台
        seed: 随机种子
        stance_distribution: 立场分布

    Returns:
        Persona列表
    """
    factory = PersonaFactory(seed=seed)
    return factory.create_batch(
        count=count,
        platform=platform,
        stance_distribution=stance_distribution,
    )
