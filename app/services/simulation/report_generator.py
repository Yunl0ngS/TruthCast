"""报告生成器 - 生成模拟结果报告"""

from typing import Optional
from collections import Counter
from dataclasses import dataclass

from app.services.simulation.models import (
    Persona, AgentAction, SimulationResult, Stance, RoleType, Platform
)
from app.services.simulation.timeline import Timeline, SimulationTick


@dataclass
class StanceSnapshot:
    """立场快照"""
    tick: int
    support: float
    oppose: float
    neutral: float
    fickle: float


@dataclass
class ViralContent:
    """爆款内容"""
    action_id: str
    agent_id: str
    content: str
    platform: Platform
    reach: int
    tick: int
    stance: Stance


class ReportGenerator:
    """模拟报告生成器"""

    def __init__(self):
        self.stance_history: list[StanceSnapshot] = []
        self.viral_contents: list[ViralContent] = []
        self.action_history: list[AgentAction] = []

    def record_tick(
        self,
        tick: SimulationTick,
        agents: list[Persona],
        actions: list[AgentAction],
    ):
        """记录一个时刻的数据"""
        # 统计立场分布
        stance_counts = Counter(a.stance for a in agents)
        total = len(agents)

        snapshot = StanceSnapshot(
            tick=tick.tick,
            support=stance_counts.get(Stance.SUPPORT, 0) / total if total > 0 else 0,
            oppose=stance_counts.get(Stance.OPPOSE, 0) / total if total > 0 else 0,
            neutral=stance_counts.get(Stance.NEUTRAL, 0) / total if total > 0 else 0,
            fickle=stance_counts.get(Stance.FICKLE, 0) / total if total > 0 else 0,
        )
        self.stance_history.append(snapshot)

        # 记录行动
        self.action_history.extend(actions)

        # 识别爆款内容（简化版：高影响力用户的发帖）
        for action in actions:
            agent = next((a for a in agents if a.id == action.agent_id), None)
            if agent and action.action_type == "post":
                if agent.influence >= 0.7:
                    self.viral_contents.append(ViralContent(
                        action_id=action.id,
                        agent_id=agent.id,
                        content=action.content[:100] if action.content else "",
                        platform=action.platform,
                        reach=int(agent.follower_count * agent.influence),
                        tick=tick.tick,
                        stance=agent.stance,
                    ))

    def generate_result(self) -> SimulationResult:
        """生成模拟结果"""
        result = SimulationResult()

        # 1. 情绪分布（最终立场）
        if self.stance_history:
            final_stance = self.stance_history[-1]
            result.sentiment_distribution = {
                "support": final_stance.support,
                "oppose": final_stance.oppose,
                "neutral": final_stance.neutral,
                "fickle": final_stance.fickle,
            }

        # 2. 观点聚类
        result.opinion_clusters = self._generate_opinion_clusters()

        # 3. 引爆点
        result.trigger_points = self._identify_trigger_points()

        # 4. 风险预警
        result.risk_warnings = self._generate_risk_warnings()

        # 5. 应对建议
        result.suggestions = self._generate_suggestions()

        # 6. 图数据（节点和边）
        result.nodes, result.edges = self._generate_graph_data()

        return result

    def _generate_opinion_clusters(self) -> list[dict]:
        """生成观点聚类"""
        clusters = []

        if not self.stance_history:
            return clusters

        final_stance = self.stance_history[-1]

        # 支持派
        if final_stance.support > 0.1:
            clusters.append({
                "stance": "support",
                "ratio": final_stance.support,
                "key_points": [
                    "认为产品/服务有改进",
                    "期待后续发展",
                    "认可官方回应",
                ],
                "representative_agents": [],
            })

        # 反对派
        if final_stance.oppose > 0.1:
            clusters.append({
                "stance": "oppose",
                "ratio": final_stance.oppose,
                "key_points": [
                    "对处理方式不满",
                    "要求更多解释",
                    "担心类似问题再发生",
                ],
                "representative_agents": [],
            })

        # 中立派
        if final_stance.neutral > 0.1:
            clusters.append({
                "stance": "neutral",
                "ratio": final_stance.neutral,
                "key_points": [
                    "观望态度",
                    "等待更多信息",
                    "理性分析中",
                ],
                "representative_agents": [],
            })

        return clusters

    def _identify_trigger_points(self) -> list[dict]:
        """识别引爆点"""
        triggers = []

        # 爆款内容作为引爆点
        for viral in self.viral_contents[:5]:  # 取前5个
            triggers.append({
                "type": "viral_post",
                "tick": viral.tick,
                "hour": viral.tick % 24,
                "day": viral.tick // 24,
                "description": f"高影响力用户发布{viral.stance.value}立场内容",
                "reach": viral.reach,
                "action_id": viral.action_id,
            })

        # 立场突变点
        for i in range(1, len(self.stance_history)):
            prev = self.stance_history[i - 1]
            curr = self.stance_history[i]

            # 检测立场变化超过5%
            for stance_name in ["support", "oppose", "neutral"]:
                prev_val = getattr(prev, stance_name)
                curr_val = getattr(curr, stance_name)

                if abs(curr_val - prev_val) > 0.05:
                    triggers.append({
                        "type": "stance_shift",
                        "tick": curr.tick,
                        "hour": curr.tick % 24,
                        "day": curr.tick // 24,
                        "description": f"{stance_name}立场比例变化{abs(curr_val - prev_val)*100:.1f}%",
                        "stance": stance_name,
                        "change": curr_val - prev_val,
                    })

        return triggers

    def _generate_risk_warnings(self) -> list[str]:
        """生成风险预警"""
        warnings = []

        if not self.stance_history:
            return warnings

        final_stance = self.stance_history[-1]

        # 反对比例过高
        if final_stance.oppose > 0.4:
            warnings.append(f"反对声音较高({final_stance.oppose*100:.1f}%)，可能引发公关危机")

        # 立场不稳定
        if final_stance.fickle > 0.3:
            warnings.append(f"墙头草比例高({final_stance.fickle*100:.1f}%)，舆论方向仍不稳定")

        # 检测立场变化趋势
        if len(self.stance_history) >= 10:
            recent = self.stance_history[-10:]

            # 反对趋势上升
            if all(recent[i].oppose <= recent[i+1].oppose for i in range(len(recent)-1)):
                warnings.append("反对声音持续上升，需及时干预")

        # 爆款内容风险
        viral_oppose = sum(1 for v in self.viral_contents if v.stance == Stance.OPPOSE)
        if viral_oppose > 3:
            warnings.append(f"出现{viral_oppose}条高影响力反对内容，可能成为舆论焦点")

        return warnings

    def _generate_suggestions(self) -> list[str]:
        """生成应对建议"""
        suggestions = []

        if not self.stance_history:
            return suggestions

        final_stance = self.stance_history[-1]

        # 基于最终立场分布
        if final_stance.support > final_stance.oppose:
            suggestions.append("舆论整体偏向正面，可继续保持当前沟通策略")
        elif final_stance.oppose > final_stance.support:
            suggestions.append("建议发布更详细的解释或道歉声明，回应公众关切")

        if final_stance.fickle > 0.3:
            suggestions.append("建议增加官方发声频率，引导舆论方向")

        # 基于风险预警
        if final_stance.oppose > 0.3:
            suggestions.append("考虑通过KOL或意见领袖传递正面信息")

        suggestions.append("持续监测舆情动态，做好应急预案")

        return suggestions

    def _generate_graph_data(self) -> tuple[list[dict], list[dict]]:
        """生成图数据（节点和边）"""
        nodes = []
        edges = []

        # 从行动历史构建图
        agent_actions: dict[str, list[AgentAction]] = {}

        for action in self.action_history:
            if action.agent_id not in agent_actions:
                agent_actions[action.agent_id] = []
            agent_actions[action.agent_id].append(action)

        # 构建节点
        for agent_id, actions in agent_actions.items():
            node = {
                "id": agent_id,
                "action_count": len(actions),
                "post_count": sum(1 for a in actions if a.action_type == "post"),
                "repost_count": sum(1 for a in actions if a.action_type == "repost"),
                "comment_count": sum(1 for a in actions if a.action_type == "comment"),
            }
            nodes.append(node)

        # 构建边（简化版：基于互动）
        # 实际应该根据具体的互动关系构建
        for action in self.action_history:
            if action.target_agent_id:
                edge = {
                    "source": action.agent_id,
                    "target": action.target_agent_id,
                    "action": action.action_type,
                    "tick": action.timestamp.isoformat() if hasattr(action, 'timestamp') else None,
                }
                edges.append(edge)

        return nodes, edges

    def get_stance_trend(self) -> list[dict]:
        """获取立场趋势数据"""
        return [
            {
                "tick": s.tick,
                "support": s.support,
                "oppose": s.oppose,
                "neutral": s.neutral,
                "fickle": s.fickle,
            }
            for s in self.stance_history
        ]
