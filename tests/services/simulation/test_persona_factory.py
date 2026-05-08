"""Agent工厂测试"""

import pytest
from app.services.simulation.persona_factory import PersonaFactory, create_agent_pool
from app.services.simulation.models import RoleType, Stance, UserType, Platform


def test_create_single_persona():
    """测试创建单个Agent"""
    factory = PersonaFactory(seed=42)
    persona = factory.create_persona(platform=Platform.WEIBO)

    assert persona.id.startswith("agent-")
    assert persona.name
    assert persona.username
    assert persona.role_type in list(RoleType)
    assert persona.platform == Platform.WEIBO
    assert 0 <= persona.influence <= 1
    assert 0 <= persona.activity <= 1


def test_create_persona_with_specific_role():
    """测试指定角色类型创建"""
    factory = PersonaFactory(seed=42)
    persona = factory.create_persona(
        platform=Platform.WEIBO,
        role_type=RoleType.KOL
    )

    assert persona.role_type == RoleType.KOL
    # KOL 应该有较高影响力
    assert persona.influence >= 0.7


def test_create_persona_with_stance():
    """测试指定立场创建"""
    factory = PersonaFactory(seed=42)
    persona = factory.create_persona(
        platform=Platform.WEIBO,
        stance=Stance.SUPPORT
    )

    assert persona.stance == Stance.SUPPORT


def test_create_batch_default_distribution():
    """测试批量创建（默认比例）"""
    factory = PersonaFactory(seed=42)
    personas = factory.create_batch(count=100, platform=Platform.WEIBO)

    assert len(personas) == 100

    # 统计角色类型分布
    role_counts = {}
    for p in personas:
        role_counts[p.role_type] = role_counts.get(p.role_type, 0) + 1

    # 应该有多种角色类型
    assert len(role_counts) > 1


def test_create_batch_with_stance_distribution():
    """测试批量创建（指定立场分布）"""
    factory = PersonaFactory(seed=42)

    stance_dist = {
        Stance.SUPPORT: 0.3,
        Stance.OPPOSE: 0.2,
        Stance.NEUTRAL: 0.5,
    }

    personas = factory.create_batch(
        count=100,
        platform=Platform.WEIBO,
        stance_distribution=stance_dist
    )

    # 统计立场分布
    stance_counts = {}
    for p in personas:
        stance_counts[p.stance] = stance_counts.get(p.stance, 0) + 1

    # 检查大致符合比例（允许一定误差）
    total = len(personas)
    support_ratio = stance_counts.get(Stance.SUPPORT, 0) / total
    oppose_ratio = stance_counts.get(Stance.OPPOSE, 0) / total
    neutral_ratio = stance_counts.get(Stance.NEUTRAL, 0) / total

    # 允许15%误差
    assert abs(support_ratio - 0.3) < 0.15
    assert abs(oppose_ratio - 0.2) < 0.15
    assert abs(neutral_ratio - 0.5) < 0.15


def test_core_user_ratio():
    """测试核心用户占比"""
    factory = PersonaFactory(seed=42, core_user_ratio=0.15)
    personas = factory.create_batch(count=500, platform=Platform.WEIBO)

    core_count = sum(1 for p in personas if p.user_type == UserType.CORE)
    core_ratio = core_count / len(personas)

    # 核心用户占比应该接近预期（允许误差）
    # KOL(8%)和OFFICIAL(5%)强制为核心用户，加上15%的其他角色
    # 预期比例约为: 8% + 5% + 15%*(100%-8%-5%) ≈ 23.95%
    assert 0.15 < core_ratio < 0.35


def test_kol_high_influence():
    """测试KOL高影响力"""
    factory = PersonaFactory(seed=42)

    # 创建多个KOL
    kols = []
    for _ in range(10):
        persona = factory.create_persona(role_type=RoleType.KOL)
        kols.append(persona)

    # KOL影响力应该在0.7-1.0范围
    for kol in kols:
        assert kol.influence >= 0.7


def test_kol_and_official_are_core_users():
    """测试KOL和OFFICIAL强制为核心用户"""
    factory = PersonaFactory(seed=42)

    # 创建KOL
    for _ in range(5):
        persona = factory.create_persona(role_type=RoleType.KOL)
        assert persona.user_type == UserType.CORE

    # 创建OFFICIAL
    for _ in range(5):
        persona = factory.create_persona(role_type=RoleType.OFFICIAL)
        assert persona.user_type == UserType.CORE


def test_temporal_pattern():
    """测试时间模式生成"""
    factory = PersonaFactory(seed=42)
    persona = factory.create_persona()

    pattern = persona.temporal_pattern
    assert len(pattern.pattern) == 24
    # 所有值应该在0-1之间
    for v in pattern.pattern:
        assert 0 <= v <= 1


def test_early_bird_pattern():
    """测试早起型时间模式"""
    factory = PersonaFactory(seed=42)
    pattern = factory._create_early_bird_pattern()

    assert len(pattern.pattern) == 24
    # 早起型应该在5-8点活跃
    assert pattern.pattern[6] > pattern.pattern[3]
    # 下午也应该有活动
    assert pattern.pattern[12] > 0


def test_create_agent_pool_convenience():
    """测试便捷函数"""
    personas = create_agent_pool(count=50, platform=Platform.XIAOHONGSHU)

    assert len(personas) == 50
    for p in personas:
        assert p.platform == Platform.XIAOHONGSHU


def test_reproducible_with_seed():
    """测试相同种子生成相同结果"""
    factory1 = PersonaFactory(seed=12345)
    factory2 = PersonaFactory(seed=12345)

    p1 = factory1.create_persona()
    p2 = factory2.create_persona()

    assert p1.name == p2.name
    assert p1.username == p2.username


def test_big_five_generation():
    """测试Big Five人格生成"""
    factory = PersonaFactory(seed=42)

    # 测试不同角色的人格特征
    normal = factory.create_persona(role_type=RoleType.NORMAL)
    rational = factory.create_persona(role_type=RoleType.RATIONAL)
    troll = factory.create_persona(role_type=RoleType.TROLL)

    # 理性派应该有更高的尽责性
    assert rational.big_five.conscientiousness > normal.big_five.conscientiousness

    # 职业喷应该有更低的宜人性
    assert troll.big_five.agreeableness < normal.big_five.agreeableness


def test_follower_count_by_user_type():
    """测试粉丝数按用户类型生成"""
    factory = PersonaFactory(seed=42)

    # 核心用户应该有更高粉丝数
    core_persona = factory.create_persona(role_type=RoleType.KOL)
    assert core_persona.follower_count >= 10000

    # 普通用户粉丝数较低
    # 强制创建普通用户
    normal_persona = factory.create_persona(role_type=RoleType.NORMAL)
    # 普通用户如果恰好不是核心用户，粉丝数应该较低
    if normal_persona.user_type == UserType.ORDINARY:
        assert normal_persona.follower_count < 10000


def test_profession_generation():
    """测试职业生成"""
    factory = PersonaFactory(seed=42)
    persona = factory.create_persona()

    assert persona.profession
    assert persona.profession_category


def test_bio_generation():
    """测试Bio生成"""
    factory = PersonaFactory(seed=42)

    # 不同角色类型应该有不同的Bio
    kol = factory.create_persona(role_type=RoleType.KOL)
    assert "领域" in kol.bio or "博主" in kol.bio or "干货" in kol.bio or "爱好者" in kol.bio

    official = factory.create_persona(role_type=RoleType.OFFICIAL)
    assert "官方" in official.bio or "认证" in official.bio


def test_role_distribution_500_agents():
    """测试500个Agent的角色分布是否符合预期"""
    factory = PersonaFactory(seed=42)
    personas = factory.create_batch(count=500, platform=Platform.WEIBO)

    # 统计各角色类型数量
    role_counts = {}
    for p in personas:
        role_counts[p.role_type] = role_counts.get(p.role_type, 0) + 1

    # 检查大致比例（允许误差）
    # NORMAL: 30%
    assert 100 < role_counts.get(RoleType.NORMAL, 0) < 180

    # KOL: 8%
    assert 25 < role_counts.get(RoleType.KOL, 0) < 55

    # OFFICIAL: 5%
    assert 10 < role_counts.get(RoleType.OFFICIAL, 0) < 40

    # TROLL: 10%
    assert 30 < role_counts.get(RoleType.TROLL, 0) < 70


def test_extreme_stance_stability():
    """测试极端粉丝立场稳定性"""
    factory = PersonaFactory(seed=42)
    extreme = factory.create_persona(role_type=RoleType.EXTREME)

    # 极端粉丝立场灵活性应该很低
    assert extreme.stance_flexibility < 0.3


def test_bystander_fickle_stance():
    """测试吃瓜群众墙头草特性"""
    factory = PersonaFactory(seed=42)
    bystander = factory.create_persona(role_type=RoleType.BYSTANDER)

    # 吃瓜群众立场灵活性应该很高
    assert bystander.stance_flexibility > 0.7
    # 默认立场应该是墙头草
    assert bystander.stance == Stance.FICKLE


def test_novice_high_conformity():
    """测试萌新高从众性"""
    factory = PersonaFactory(seed=42)
    novice = factory.create_persona(role_type=RoleType.NOVICE)

    # 萌新从众度应该很高
    assert novice.conformity > 0.5


def test_troll_oppose_stance():
    """测试职业喷默认反对立场"""
    factory = PersonaFactory(seed=42)
    troll = factory.create_persona(role_type=RoleType.TROLL)

    # 职业喷默认应该是反对立场
    assert troll.stance == Stance.OPPOSE
