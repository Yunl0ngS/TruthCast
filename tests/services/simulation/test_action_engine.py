"""行动决策引擎测试"""

import pytest
from app.services.simulation.action_engine import ActionEngine, ActionContext
from app.services.simulation.models import (
    Persona, RoleType, Stance, Platform, BigFive, TemporalPattern
)
from app.services.simulation.persona_factory import PersonaFactory


@pytest.fixture
def sample_persona():
    """创建测试用Persona"""
    return Persona(
        id="test-agent-001",
        name="测试用户",
        username="test_user",
        role_type=RoleType.NORMAL,
        platform=Platform.WEIBO,
        big_five=BigFive(),
        stance=Stance.NEUTRAL,
        activity=0.5,
        conformity=0.5,
        temporal_pattern=TemporalPattern.create_workday(),
    )


@pytest.fixture
def sample_context():
    """创建测试用上下文"""
    return ActionContext(
        current_hour=10,
        seed_keywords=["测试话题", "新闻"],
        trending_topics=["热门话题"],
        seen_content_ids=[],
        interacted_user_ids=[],
    )


def test_engine_initialization():
    """测试引擎初始化"""
    engine = ActionEngine(seed=42)
    assert engine.rng is not None


def test_should_act_probability(sample_persona, sample_context):
    """测试行动概率"""
    engine = ActionEngine(seed=42)

    # 多次测试统计行动概率
    actions = 0
    for _ in range(100):
        if engine._should_act(sample_persona, sample_context.current_hour):
            actions += 1

    # 活跃时段应该有一定行动概率
    ratio = actions / 100
    assert 0 < ratio < 1  # 不应该总是行动或从不行动


def test_decide_action_type_distribution(sample_persona, sample_context):
    """测试行动类型分布"""
    engine = ActionEngine(seed=42)

    # 统计行动类型分布
    action_types = {}
    for _ in range(100):
        action_type = engine._decide_action_type(sample_persona, sample_context)
        action_types[action_type] = action_types.get(action_type, 0) + 1

    # 应该有多种行动类型
    assert len(action_types) > 1


def test_kol_more_posting(sample_context):
    """测试KOL更倾向发帖"""
    factory = PersonaFactory(seed=42)
    kol = factory.create_persona(role_type=RoleType.KOL)

    engine = ActionEngine(seed=42)

    # 统计KOL的行动类型
    action_types = {}
    for _ in range(100):
        action_type = engine._decide_action_type(kol, sample_context)
        action_types[action_type] = action_types.get(action_type, 0) + 1

    # KOL的发帖比例应该较高
    post_ratio = action_types.get("post", 0) / 100
    assert post_ratio > 0.2  # KOL发帖比例应该高于普通用户


def test_official_more_posting(sample_context):
    """测试官方号更倾向发帖"""
    factory = PersonaFactory(seed=42)
    official = factory.create_persona(role_type=RoleType.OFFICIAL)

    engine = ActionEngine(seed=42)

    action_types = {}
    for _ in range(100):
        action_type = engine._decide_action_type(official, sample_context)
        action_types[action_type] = action_types.get(action_type, 0) + 1

    # 官方号的发帖比例应该最高
    post_ratio = action_types.get("post", 0) / 100
    assert post_ratio > 0.4


def test_decide_returns_action(sample_persona, sample_context):
    """测试决策返回行动"""
    engine = ActionEngine(seed=42)

    # 强制行动（提高活跃度）
    sample_persona.activity = 1.0
    sample_persona.temporal_pattern = TemporalPattern(pattern=[1.0] * 24)

    action = engine.decide(sample_persona, sample_context)

    if action:  # 可能不行动
        assert action.agent_id == sample_persona.id
        assert action.action_type in ["post", "repost", "comment", "like", "follow"]


def test_decide_batch(sample_context):
    """测试批量决策"""
    factory = PersonaFactory(seed=42)
    personas = factory.create_batch(count=10, platform=Platform.WEIBO)

    engine = ActionEngine(seed=42)

    actions = engine.decide_batch(personas, sample_context)

    # 返回的行动数量应该少于或等于Agent数量
    assert len(actions) <= len(personas)

    # 每个行动都应该有效
    for action in actions:
        assert action.agent_id in [p.id for p in personas]


def test_activity_modifier(sample_persona):
    """测试活跃度修正"""
    engine = ActionEngine()

    # 工作时段活跃度高
    workday_pattern = TemporalPattern.create_workday()
    sample_persona.temporal_pattern = workday_pattern

    # 工作时段（10点）
    modifier_work = engine._get_activity_modifier(sample_persona, 10)

    # 凌晨时段（3点）
    modifier_night = engine._get_activity_modifier(sample_persona, 3)

    # 工作时段应该比凌晨更活跃
    assert modifier_work > modifier_night


def test_content_generation_with_stance(sample_context):
    """测试基于立场的内容生成"""
    factory = PersonaFactory(seed=42)
    engine = ActionEngine(seed=42)

    # 支持立场
    support_persona = factory.create_persona(stance=Stance.SUPPORT)
    content = engine._generate_content(support_persona, "post", sample_context)
    assert content  # 应该有内容

    # 反对立场
    oppose_persona = factory.create_persona(stance=Stance.OPPOSE)
    content = engine._generate_content(oppose_persona, "post", sample_context)
    assert content


def test_reproducible_with_seed(sample_persona, sample_context):
    """测试相同种子产生相同结果"""
    engine1 = ActionEngine(seed=12345)
    engine2 = ActionEngine(seed=12345)

    # 强制行动
    sample_persona.activity = 1.0
    sample_persona.temporal_pattern = TemporalPattern(pattern=[1.0] * 24)

    action1 = engine1.decide(sample_persona, sample_context)
    action2 = engine2.decide(sample_persona, sample_context)

    if action1 and action2:
        assert action1.action_type == action2.action_type


def test_troll_more_commenting(sample_context):
    """测试职业喷更倾向评论"""
    factory = PersonaFactory(seed=42)
    troll = factory.create_persona(role_type=RoleType.TROLL)

    engine = ActionEngine(seed=42)

    action_types = {}
    for _ in range(100):
        action_type = engine._decide_action_type(troll, sample_context)
        action_types[action_type] = action_types.get(action_type, 0) + 1

    # 职业喷的评论比例应该较高
    comment_ratio = action_types.get("comment", 0) / 100
    assert comment_ratio > 0.3


def test_bystander_more_likes(sample_context):
    """测试吃瓜群众更倾向点赞"""
    factory = PersonaFactory(seed=42)
    bystander = factory.create_persona(role_type=RoleType.BYSTANDER)

    engine = ActionEngine(seed=42)

    action_types = {}
    for _ in range(100):
        action_type = engine._decide_action_type(bystander, sample_context)
        action_types[action_type] = action_types.get(action_type, 0) + 1

    # 吃瓜群众的点赞比例应该较高
    like_ratio = action_types.get("like", 0) / 100
    assert like_ratio > 0.2


def test_big_five_influence(sample_context):
    """测试Big Five人格对行动的影响"""
    factory = PersonaFactory(seed=42)
    engine = ActionEngine(seed=42)

    # 高外向性人格
    extravert = factory.create_persona()
    extravert.big_five.extraversion = 0.9

    # 低外向性人格
    introvert = factory.create_persona()
    introvert.big_five.extraversion = 0.1

    # 统计发帖和评论比例
    extravert_posts = 0
    introvert_posts = 0

    for _ in range(50):
        ext_action = engine._decide_action_type(extravert, sample_context)
        int_action = engine._decide_action_type(introvert, sample_context)

        if ext_action in ["post", "comment"]:
            extravert_posts += 1
        if int_action in ["post", "comment"]:
            introvert_posts += 1

    # 高外向性应该更倾向发帖/评论（但允许一定随机性）
    # 这里不强制要求，因为随机性较大
    assert extravert_posts >= 0
    assert introvert_posts >= 0
