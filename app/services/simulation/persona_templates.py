"""人格模板和角色配置"""

from typing import Optional
from pydantic import BaseModel, Field
from app.services.simulation.models import (
    RoleType, Stance, UserType, BigFive, Platform
)


class RoleConfig(BaseModel):
    """角色类型配置"""

    role_type: RoleType
    ratio: float  # 占比 0-1
    description: str

    # Big Five 人格倾向范围 (min, max)
    openness_range: tuple[float, float] = (0.3, 0.7)
    conscientiousness_range: tuple[float, float] = (0.3, 0.7)
    extraversion_range: tuple[float, float] = (0.3, 0.7)
    agreeableness_range: tuple[float, float] = (0.3, 0.7)
    neuroticism_range: tuple[float, float] = (0.3, 0.7)

    # 行为参数范围
    influence_range: tuple[float, float] = (0.1, 0.5)
    activity_range: tuple[float, float] = (0.3, 0.7)
    conformity_range: tuple[float, float] = (0.3, 0.7)
    expertise_range: tuple[float, float] = (0.1, 0.5)

    # 立场配置
    default_stance: Stance = Stance.NEUTRAL
    stance_flexibility_range: tuple[float, float] = (0.3, 0.7)

    # 发言风格
    language_styles: list[str] = Field(default_factory=lambda: ["neutral"])

    # 是否可以是核心用户
    can_be_core: bool = True


# 8种角色类型的默认配置
ROLE_CONFIGS: dict[RoleType, RoleConfig] = {
    RoleType.NORMAL: RoleConfig(
        role_type=RoleType.NORMAL,
        ratio=0.30,
        description="普通网友，沉默大多数，跟风转发，情绪化",
        openness_range=(0.3, 0.6),
        conscientiousness_range=(0.2, 0.5),
        extraversion_range=(0.3, 0.6),
        agreeableness_range=(0.4, 0.7),
        neuroticism_range=(0.4, 0.8),
        influence_range=(0.1, 0.4),
        activity_range=(0.2, 0.5),
        conformity_range=(0.6, 0.9),  # 高从众
        expertise_range=(0.1, 0.3),
        default_stance=Stance.NEUTRAL,
        stance_flexibility_range=(0.5, 0.9),  # 立场易变
        language_styles=["casual", "emotional"],
    ),

    RoleType.RATIONAL: RoleConfig(
        role_type=RoleType.RATIONAL,
        ratio=0.10,
        description="理性分析派，摆数据讲逻辑，援引权威",
        openness_range=(0.6, 0.9),
        conscientiousness_range=(0.6, 0.9),
        extraversion_range=(0.3, 0.6),
        agreeableness_range=(0.3, 0.6),
        neuroticism_range=(0.1, 0.4),
        influence_range=(0.3, 0.6),
        activity_range=(0.4, 0.7),
        conformity_range=(0.2, 0.4),  # 低从众
        expertise_range=(0.5, 0.8),
        default_stance=Stance.NEUTRAL,
        stance_flexibility_range=(0.1, 0.3),  # 立场稳定
        language_styles=["professional", "rational"],
    ),

    RoleType.KOL: RoleConfig(
        role_type=RoleType.KOL,
        ratio=0.08,
        description="KOL/意见领袖，有影响力，专业性强",
        openness_range=(0.5, 0.8),
        conscientiousness_range=(0.5, 0.8),
        extraversion_range=(0.5, 0.9),
        agreeableness_range=(0.3, 0.6),
        neuroticism_range=(0.2, 0.5),
        influence_range=(0.7, 1.0),  # 高影响力
        activity_range=(0.6, 0.9),
        conformity_range=(0.2, 0.4),
        expertise_range=(0.6, 0.9),
        default_stance=Stance.NEUTRAL,
        stance_flexibility_range=(0.2, 0.5),
        language_styles=["professional", "casual"],
        can_be_core=True,  # 强制为核心用户
    ),

    RoleType.EXTREME: RoleConfig(
        role_type=RoleType.EXTREME,
        ratio=0.10,
        description="极端粉丝，立场极端，情绪化严重",
        openness_range=(0.2, 0.4),
        conscientiousness_range=(0.2, 0.5),
        extraversion_range=(0.4, 0.8),
        agreeableness_range=(0.1, 0.4),
        neuroticism_range=(0.6, 0.9),
        influence_range=(0.2, 0.5),
        activity_range=(0.5, 0.9),
        conformity_range=(0.5, 0.8),
        expertise_range=(0.1, 0.4),
        default_stance=Stance.SUPPORT,  # 或OPPOSE，取决于种子材料
        stance_flexibility_range=(0.0, 0.2),  # 立场极端稳定
        language_styles=["emotional"],
    ),

    RoleType.BYSTANDER: RoleConfig(
        role_type=RoleType.BYSTANDER,
        ratio=0.12,
        description="吃瓜群众，墙头草，看热闹",
        openness_range=(0.4, 0.7),
        conscientiousness_range=(0.2, 0.4),
        extraversion_range=(0.3, 0.6),
        agreeableness_range=(0.4, 0.7),
        neuroticism_range=(0.3, 0.6),
        influence_range=(0.1, 0.3),
        activity_range=(0.3, 0.6),
        conformity_range=(0.7, 1.0),  # 极高从众
        expertise_range=(0.1, 0.3),
        default_stance=Stance.FICKLE,  # 墙头草
        stance_flexibility_range=(0.8, 1.0),  # 极易变
        language_styles=["casual"],
    ),

    RoleType.OFFICIAL: RoleConfig(
        role_type=RoleType.OFFICIAL,
        ratio=0.05,
        description="官方/媒体号，代表机构立场",
        openness_range=(0.3, 0.5),
        conscientiousness_range=(0.7, 0.9),
        extraversion_range=(0.3, 0.5),
        agreeableness_range=(0.5, 0.7),
        neuroticism_range=(0.1, 0.3),
        influence_range=(0.8, 1.0),  # 高影响力
        activity_range=(0.3, 0.5),
        conformity_range=(0.1, 0.3),
        expertise_range=(0.7, 1.0),
        default_stance=Stance.NEUTRAL,
        stance_flexibility_range=(0.0, 0.1),  # 立场固定
        language_styles=["professional"],
        can_be_core=True,
    ),

    RoleType.TROLL: RoleConfig(
        role_type=RoleType.TROLL,
        ratio=0.10,
        description="专业黑/职业喷，以挑刺为乐",
        openness_range=(0.3, 0.6),
        conscientiousness_range=(0.2, 0.4),
        extraversion_range=(0.4, 0.7),
        agreeableness_range=(0.1, 0.3),  # 低宜人性
        neuroticism_range=(0.5, 0.8),
        influence_range=(0.2, 0.5),
        activity_range=(0.5, 0.8),
        conformity_range=(0.3, 0.5),
        expertise_range=(0.3, 0.6),
        default_stance=Stance.OPPOSE,
        stance_flexibility_range=(0.1, 0.3),
        language_styles=["emotional", "casual"],
    ),

    RoleType.NOVICE: RoleConfig(
        role_type=RoleType.NOVICE,
        ratio=0.15,
        description="萌新/小白，经验不足，易被误导",
        openness_range=(0.5, 0.8),
        conscientiousness_range=(0.3, 0.5),
        extraversion_range=(0.3, 0.6),
        agreeableness_range=(0.5, 0.8),
        neuroticism_range=(0.3, 0.6),
        influence_range=(0.1, 0.3),
        activity_range=(0.2, 0.5),
        conformity_range=(0.6, 0.9),  # 高从众
        expertise_range=(0.0, 0.2),
        default_stance=Stance.NEUTRAL,
        stance_flexibility_range=(0.6, 0.9),
        language_styles=["casual"],
    ),
}


class ProfessionCategory(BaseModel):
    """职业类别配置"""

    category: str
    ratio: float
    professions: list[str]
    description: str


# 职业背景池
PROFESSION_CATEGORIES: list[ProfessionCategory] = [
    ProfessionCategory(
        category="学生",
        ratio=0.20,
        professions=["大学生", "研究生", "高中生", "留学生"],
        description="情绪化、流行语多"
    ),
    ProfessionCategory(
        category="职场白领",
        ratio=0.25,
        professions=["程序员", "产品经理", "运营", "市场", "HR", "财务", "行政"],
        description="理性、关心职场话题"
    ),
    ProfessionCategory(
        category="技术从业者",
        ratio=0.15,
        professions=["工程师", "架构师", "数据分析师", "AI研究员", "测试工程师"],
        description="重视数据、逻辑性强"
    ),
    ProfessionCategory(
        category="自由职业",
        ratio=0.10,
        professions=["自媒体", "设计师", "摄影师", "作家", "主播", "博主"],
        description="观点鲜明、个人色彩强"
    ),
    ProfessionCategory(
        category="退休/全职",
        ratio=0.10,
        professions=["退休人员", "全职妈妈", "全职爸爸"],
        description="关心民生、家长里短"
    ),
    ProfessionCategory(
        category="其他",
        ratio=0.20,
        professions=["待业", "创业者", "公务员", "教师", "医生", "律师", "销售"],
        description="泛化角色"
    ),
]


# 姓名生成器数据
FIRST_NAMES_MALE = [
    "伟", "强", "磊", "洋", "勇", "军", "杰", "涛", "明", "辉",
    "鹏", "华", "飞", "刚", "超", "波", "平", "健", "林", "斌"
]

FIRST_NAMES_FEMALE = [
    "芳", "娜", "敏", "静", "丽", "婷", "莉", "燕", "艳", "玲",
    "梅", "红", "华", "霞", "娟", "洁", "颖", "慧", "琳", "欣"
]

LAST_NAMES = [
    "王", "李", "张", "刘", "陈", "杨", "赵", "黄", "周", "吴",
    "徐", "孙", "胡", "朱", "高", "林", "何", "郭", "马", "罗"
]

# 用户名前缀
USERNAME_PREFIXES = [
    "user", "hello", "hi", "happy", "cool", "best", "top", "super",
    "nice", "good", "great", "awesome", "amazing", "lovely", "dear"
]

# Bio 模板
BIO_TEMPLATES = {
    RoleType.NORMAL: [
        "普通网友一枚",
        "随便看看",
        "记录生活",
        "佛系用户",
    ],
    RoleType.RATIONAL: [
        "用数据说话",
        "理性分析，客观评论",
        "关注事实真相",
        "独立思考者",
    ],
    RoleType.KOL: [
        "专注{topic}领域",
        "{topic}博主 | 合作私信",
        "分享{topic}干货",
        "{topic}爱好者",
    ],
    RoleType.EXTREME: [
        "永远支持{target}",
        "{target}一生推",
        "黑粉勿扰",
        "死忠粉认证",
    ],
    RoleType.BYSTANDER: [
        "吃瓜群众",
        "围观群众",
        "看热闹不嫌事大",
        "路人甲",
    ],
    RoleType.OFFICIAL: [
        "官方账号",
        "媒体认证账号",
        "企业官方",
        "政务号",
    ],
    RoleType.TROLL: [
        "专业吐槽",
        "键盘侠本侠",
        "我有话说",
        "不吐不快",
    ],
    RoleType.NOVICE: [
        "萌新报到",
        "小白求带",
        "学习中...",
        "请多指教",
    ],
}
