"""
舆情预演服务 - LLM 驱动版

多阶段推理:
1. 情绪与立场分析 -> 基于文本特征预测情绪分布
2. 叙事分支生成 -> 生成 3-5 条可能的舆论走向
3. 引爆点识别 -> 识别高风险传播节点
4. 应对建议生成 -> 针对性策略建议
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logger import get_logger
from app.schemas.detect import (
    ActionItem,
    ClaimItem,
    EvidenceItem,
    NarrativeItem,
    ReportResponse,
    SimulateResponse,
    SuggestionData,
    TimelineItem,
)
from app.services.json_utils import serialize_for_json

logger = get_logger(__name__)

SIMULATION_LLM_ENABLED = os.getenv("TRUTHCAST_SIMULATION_LLM_ENABLED", "false").lower() == "true"
SIMULATION_LLM_MODEL = os.getenv("TRUTHCAST_SIMULATION_LLM_MODEL", "")
SIMULATION_LLM_BASE_URL = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1")
SIMULATION_LLM_API_KEY = os.getenv("TRUTHCAST_LLM_API_KEY", "")
SIMULATION_MAX_NARRATIVES = int(os.getenv("TRUTHCAST_SIMULATION_MAX_NARRATIVES", "4"))
SIMULATION_TIMEOUT_SEC = int(os.getenv("TRUTHCAST_SIMULATION_TIMEOUT_SEC", "45"))
SIMULATION_MAX_RETRIES = int(os.getenv("TRUTHCAST_SIMULATION_MAX_RETRIES", "2"))
SIMULATION_RETRY_DELAY = int(os.getenv("TRUTHCAST_SIMULATION_RETRY_DELAY", "2"))
DEBUG_SIMULATION = os.getenv("TRUTHCAST_DEBUG_SIMULATION", "true").lower() == "true"

_RISK_LABEL_ZH = {
    "credible": "可信",
    "suspicious": "可疑",
    "high_risk": "高风险",
    "needs_context": "需要补充语境",
    "likely_misinformation": "疑似不实信息",
}

_RISK_LEVEL_ZH = {
    "low": "低",
    "medium": "中",
    "high": "高",
    "critical": "严重",
}


def _zh_risk_label(label: str) -> str:
    return _RISK_LABEL_ZH.get(label, label)


def _zh_risk_level(level: str) -> str:
    return _RISK_LEVEL_ZH.get(level, level)


def _record_simulation_trace(stage: str, payload: dict[str, Any]) -> None:
    """记录舆情预演 trace 日志"""
    if not DEBUG_SIMULATION:
        return

    try:
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)

        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "simulation_trace.jsonl")

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "payload": serialize_for_json(payload),
        }
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.error("写入 simulation trace 失败: %s", exc)


def _call_llm_sync(prompt: str, step_name: str, timeout: int = SIMULATION_TIMEOUT_SEC) -> dict | None:
    """同步调用 LLM，返回解析后的 JSON，支持自动重试"""
    if not SIMULATION_LLM_ENABLED or not SIMULATION_LLM_API_KEY:
        logger.info("[Simulation] LLM not enabled or no API key, using rule fallback")
        return None

    import httpx
    import time

    headers = {
        "Authorization": f"Bearer {SIMULATION_LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": SIMULATION_LLM_MODEL or "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是舆情分析专家，擅长预测舆论走向和传播风险。输出必须为严格的 JSON 格式，不要包含任何解释性文字。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.7,
        "max_tokens": 3000,
    }

    last_error: str | None = None
    
    for attempt in range(1, SIMULATION_MAX_RETRIES + 1):
        try:
            _record_simulation_trace(
                f"{step_name}_llm_request_attempt{attempt}",
                {
                    "endpoint": f"{SIMULATION_LLM_BASE_URL}/chat/completions",
                    "timeout": timeout,
                    "attempt": attempt,
                    "max_retries": SIMULATION_MAX_RETRIES,
                },
            )

            with httpx.Client(timeout=timeout) as client:
                resp = client.post(
                    f"{SIMULATION_LLM_BASE_URL}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                raw_body = resp.json()
                content_raw = raw_body["choices"][0]["message"]["content"]
                content = content_raw.strip()

                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                from app.services.json_utils import safe_json_loads
                
                parsed = safe_json_loads(content, f"simulation_{step_name}")
                if parsed is not None:
                    if attempt > 1:
                        logger.info(f"[Simulation] {step_name} succeeded on attempt {attempt}")
                    _record_simulation_trace(
                        f"{step_name}_llm_response",
                        {
                            "attempt": attempt,
                            "parsed_json": parsed,
                        },
                    )
                    return parsed
                
                last_error = "JSON parse failed"
                logger.warning(f"[Simulation] {step_name} JSON parse failed on attempt {attempt}")

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[Simulation] {step_name} LLM call failed on attempt {attempt}/{SIMULATION_MAX_RETRIES}: {e}")
            _record_simulation_trace(f"{step_name}_llm_error_attempt{attempt}", {"error": str(e), "attempt": attempt})

        if attempt < SIMULATION_MAX_RETRIES:
            logger.info(f"[Simulation] {step_name} retrying in {SIMULATION_RETRY_DELAY}s...")
            time.sleep(SIMULATION_RETRY_DELAY)

    logger.warning(f"[Simulation] {step_name} all {SIMULATION_MAX_RETRIES} attempts failed, using rule fallback")
    _record_simulation_trace(f"{step_name}_llm_all_retries_failed", {"error": last_error, "total_attempts": SIMULATION_MAX_RETRIES})
    return None


def _get_current_time_context() -> str:
    """获取当前时间上下文"""
    now = datetime.now(timezone.utc)
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = now.astimezone(beijing_tz)
    return f"当前时间: {now_beijing.strftime('%Y年%m月%d日 %H:%M')} (北京时间)"


def _build_context_summary(
    text: str,
    claims: list[ClaimItem] | None,
    evidences: list[EvidenceItem] | None,
    report: ReportResponse | None,
) -> str:
    """构建上下文摘要"""
    parts = [_get_current_time_context()]
    parts.append(f"\n【待传播内容】\n{text[:500]}")

    if claims:
        parts.append(f"\n【关键主张】({len(claims)} 条)")
        for i, c in enumerate(claims[:3], 1):
            parts.append(f"{i}. {c.claim_text[:100]}")

    if evidences:
        support = sum(1 for e in evidences if e.stance == "support")
        refute = sum(1 for e in evidences if e.stance == "refute")
        insufficient = sum(1 for e in evidences if e.stance == "insufficient")
        parts.append(f"\n【证据情况】支持:{support} / 反驳:{refute} / 不足:{insufficient}")

    if report:
        risk_label_zh = _zh_risk_label(report.risk_label)
        risk_level_zh = _zh_risk_level(report.risk_level)
        parts.append(f"\n【风险评级】{risk_label_zh}（{risk_level_zh}风险，分数:{report.risk_score}）")
        if report.suspicious_points:
            parts.append("【可疑点】" + " / ".join(report.suspicious_points[:3]))

    return "\n".join(parts)


def _analyze_emotion_stance(
    text: str,
    claims: list[ClaimItem] | None,
    report: ReportResponse | None,
    platform: str,
    comments: list[str],
) -> dict[str, Any]:
    """Step 1: 情绪与立场分析"""

    current_time = _get_current_time_context()
    prompt = f"""
请分析以下内容在社交平台传播时可能引发的情绪分布和立场分化。

{current_time}

{{
  "platform": "{platform}",
  "content_preview": "{text[:300]}",
  "risk_level": "{_zh_risk_label(report.risk_label) if report else '未知'}",
  "existing_comments": {json.dumps(comments[:5], ensure_ascii=False)}
}}

分析要求：
1. 情绪分布：预测愤怒、恐惧、悲伤、惊讶、中性五种情绪的占比（总和=1）
2. 立场分布：预测支持、质疑、中立三种立场的占比（总和=1）
3. 考虑因素：内容敏感度、是否有官方回应、证据充分性、平台用户特征
4. 时间判断：结合当前时间判断内容中提及的时间是否合理，是否存在"旧闻新炒"或"未来预测"的情况

输出严格 JSON 格式：
{{
  "emotion_distribution": {{
    "anger": 0.0-1.0,
    "fear": 0.0-1.0,
    "sadness": 0.0-1.0,
    "surprise": 0.0-1.0,
    "neutral": 0.0-1.0
  }},
  "stance_distribution": {{
    "support": 0.0-1.0,
    "doubt": 0.0-1.0,
    "neutral": 0.0-1.0
  }},
  "emotion_drivers": ["驱动因素1", "驱动因素2"],
  "stance_drivers": ["立场分化原因1", "立场分化原因2"]
}}
"""

    result = _call_llm_sync(prompt, "step1_emotion")

    if result:
        output = {
            "emotion_distribution": result.get("emotion_distribution", {}),
            "stance_distribution": result.get("stance_distribution", {}),
            "emotion_drivers": result.get("emotion_drivers", []),
            "stance_drivers": result.get("stance_drivers", []),
            "path": "llm",
        }
        _record_simulation_trace("step1_emotion_output", output)
        return output

    fallback = _fallback_emotion_stance(text, report, comments)
    _record_simulation_trace("step1_emotion_fallback", {"result": fallback, "path": "rule"})
    return fallback


def _fallback_emotion_stance(
    text: str, report: ReportResponse | None, comments: list[str]
) -> dict[str, Any]:
    """情绪立场分析规则兜底"""
    lowered = text.lower()

    anger = 0.15
    fear = 0.15
    sadness = 0.10
    surprise = 0.20
    neutral = 0.40

    trigger_words = ["震惊", "shocking", "breaking", "紧急", "urgent", "必转", "惊天", "曝光"]
    if any(w in lowered for w in trigger_words):
        anger, fear, surprise = 0.30, 0.25, 0.25
        neutral = 0.20

    support, doubt, neutral_stance = 0.25, 0.45, 0.30

    if report and report.risk_score >= 70:
        doubt = 0.55
        support = 0.20

    if any("官方" in c or "通报" in c for c in comments):
        support, doubt = 0.40, 0.35

    return {
        "emotion_distribution": {
            "anger": round(anger, 2),
            "fear": round(fear, 2),
            "sadness": round(sadness, 2),
            "surprise": round(surprise, 2),
            "neutral": round(neutral, 2),
        },
        "stance_distribution": {
            "support": round(support, 2),
            "doubt": round(doubt, 2),
            "neutral": round(neutral_stance, 2),
        },
        "emotion_drivers": ["内容包含情绪触发词"],
        "stance_drivers": ["风险评级影响用户信任度"],
    }


def _generate_narratives(
    context: str,
    emotion_result: dict,
    report: ReportResponse | None,
    platform: str,
    time_window_hours: int,
) -> list[NarrativeItem]:
    """Step 2: 叙事分支生成"""

    prompt = f"""
基于以下信息，预测未来 {time_window_hours} 小时内舆论可能出现的 {SIMULATION_MAX_NARRATIVES} 条叙事分支。

{context}

当前情绪分布: {json.dumps(emotion_result.get("emotion_distribution", {}), ensure_ascii=False)}
当前立场分布: {json.dumps(emotion_result.get("stance_distribution", {}), ensure_ascii=False)}
风险等级: {_zh_risk_label(report.risk_label) if report else '未知'}

叙事分支要求：
1. 每条分支代表一种可能的舆论走向
2. 包含：标题、立场倾向、发生概率(0-1)、触发关键词、代表性言论
3. 概率总和不超过 1.0
4. 考虑：情绪演变、官方回应、KOL 转发、证据反转等变量
5. 时间判断：结合当前时间分析内容时效性，判断是否存在"旧闻新炒"、"时间错位"等问题

输出严格 JSON 格式：
{{
  "narratives": [
    {{
      "title": "叙事标题（简短有力）",
      "stance": "support|doubt|neutral|mixed",
      "probability": 0.0-1.0,
      "trigger_keywords": ["关键词1", "关键词2"],
      "sample_message": "代表性用户评论或传播文案"
    }}
  ]
}}
"""

    result = _call_llm_sync(prompt, "step2_narrative")

    if result and "narratives" in result:
        narratives = []
        for i, n in enumerate(result["narratives"][:SIMULATION_MAX_NARRATIVES]):
            raw_keywords = n.get("trigger_keywords", [])
            if isinstance(raw_keywords, str):
                keywords = [k.strip() for k in raw_keywords.replace(",", "，").split("，") if k.strip()]
            elif isinstance(raw_keywords, list):
                keywords = [str(k).strip() for k in raw_keywords if k]
            else:
                keywords = []
            
            narratives.append(
                NarrativeItem(
                    title=str(n.get("title", f"叙事分支 {i+1}")),
                    stance=str(n.get("stance", "neutral")),
                    probability=min(1.0, max(0.0, float(n.get("probability", 0.25) or 0.25))),
                    trigger_keywords=keywords[:5],
                    sample_message=str(n.get("sample_message", "")),
                )
            )
        _record_simulation_trace("step2_narrative_output", {"narratives": [n.model_dump() for n in narratives], "path": "llm"})
        return narratives

    fallback = _fallback_narratives(report, platform)
    _record_simulation_trace("step2_narrative_fallback", {"narratives": [n.model_dump() for n in fallback], "path": "rule"})
    return fallback


def _fallback_narratives(report: ReportResponse | None, platform: str) -> list[NarrativeItem]:
    """叙事生成规则兜底"""
    risk = report.risk_score if report else 50

    narratives = [
        NarrativeItem(
            title="情绪化转发导致快速扩散",
            stance="doubt",
            probability=0.40 if risk >= 60 else 0.25,
            trigger_keywords=["震惊", "必转", "内部消息"],
            sample_message="用户倾向于先转发后核验，扩散速度快于澄清速度。",
        ),
        NarrativeItem(
            title="官方澄清扭转舆论走向",
            stance="support",
            probability=0.35,
            trigger_keywords=["官方通报", "完整证据", "权威来源"],
            sample_message="官方发布带证据的澄清后，讨论热度逐渐回落。",
        ),
        NarrativeItem(
            title="观点分化形成持续争议",
            stance="mixed",
            probability=0.25,
            trigger_keywords=["剪辑片段", "语境争议", "断章取义"],
            sample_message="不同阵营围绕不完整证据持续争论，真相被淹没。",
        ),
    ]

    return narratives


def _identify_flashpoints(
    context: str,
    narratives: list[NarrativeItem],
    platform: str,
    time_window_hours: int,
) -> tuple[list[str], list[dict]]:
    """Step 3: 引爆点识别"""

    prompt = f"""
基于以下信息，识别未来 {time_window_hours} 小时内可能出现的高风险引爆点。

{context}

可能的叙事分支:
{json.dumps([{"title": n.title, "probability": n.probability} for n in narratives], ensure_ascii=False)}

平台: {platform}

引爆点要求：
1. 识别 2-4 个可能引发舆论爆发的关键节点
2. 包含：描述、预计时间、风险等级、触发条件
3. 考虑：KOL 介入、媒体跟进、官方回应、证据反转等
4. 时间判断：结合上下文中的当前时间分析内容时效性，判断是否存在"旧闻新炒"、"时间错位"等引爆因素

输出严格 JSON 格式：
{{
  "flashpoints": [
    {{
      "description": "引爆点描述",
      "estimated_time": "预计发生时间（相对时间）",
      "risk_level": "low|medium|high|critical",
      "trigger_condition": "触发条件"
    }}
  ],
  "timeline": [
    {{
      "hour": 预计小时数,
      "event": "事件描述",
      "expected_reach": "预计触达人数级别"
    }}
  ]
}}
"""

    result = _call_llm_sync(prompt, "step3_flashpoint")

    if result:
        flashpoints = [fp.get("description", "") for fp in result.get("flashpoints", [])]
        timeline = result.get("timeline", [])
        _record_simulation_trace("step3_flashpoint_output", {"flashpoints": flashpoints, "timeline": timeline, "path": "llm"})
        return flashpoints, timeline

    fallback_fp, fallback_tl = _fallback_flashpoints(platform, time_window_hours)
    _record_simulation_trace("step3_flashpoint_fallback", {"flashpoints": fallback_fp, "timeline": fallback_tl, "path": "rule"})
    return fallback_fp, fallback_tl


def _fallback_flashpoints(platform: str, time_window_hours: int) -> tuple[list[str], list[dict]]:
    """引爆点规则兜底"""
    flashpoints = [
        f"{platform} 平台出现断章取义片段传播",
        f"前 {time_window_hours // 3} 小时谣言扩散放大风险较高",
        "KOL 转发可能引发二次传播高峰",
    ]

    timeline = [
        {"hour": 1, "event": "初始发布，小范围传播", "expected_reach": "百级"},
        {"hour": 6, "event": "情绪发酵，转发加速", "expected_reach": "万级"},
        {"hour": 12, "event": "媒体跟进或官方回应", "expected_reach": "十万级"},
    ]

    return flashpoints, timeline


def _generate_suggestion(
    context: str,
    emotion_result: dict,
    narratives: list[NarrativeItem],
    flashpoints: list[str],
    report: ReportResponse | None,
    detected_scenario: str | None = None,
) -> SuggestionData:
    """Step 4: 应对建议生成（结构化 + 场景差异化 + 多维度）"""

    scenario = detected_scenario or report.detected_scenario if report else "general"
    risk_level = report.risk_level if report else "medium"
    risk_score = report.risk_score if report else 50

    prompt = f"""
你是舆情应对专家，基于以下分析生成结构化应对建议。

【上下文】
{context}

【分析结果】
- 风险等级: {_zh_risk_level(risk_level)}（分数: {risk_score}）
- 风险标签: {_zh_risk_label(report.risk_label) if report else '未知'}
- 场景类型: {scenario}
- 情绪分布: {json.dumps(emotion_result.get("emotion_distribution", {}), ensure_ascii=False)}
- 主要叙事: {json.dumps([n.title for n in narratives], ensure_ascii=False)}
- 引爆点: {json.dumps(flashpoints[:3], ensure_ascii=False)}

【输出要求】
1. 按优先级（urgent/high/medium）分类行动项
2. 按维度（official/media/platform/user）分类行动项
3. 每项包含：具体行动、建议时间、责任方
4. 综合摘要不超过 80 字
5. 总共 4-6 条行动项
6. 严格使用指定字段名，不要使用 action_item、coordinated_action 等变体
7. 时间判断：结合上下文中的当前时间，分析内容时效性，如发现"旧闻新炒"、"时间错位"等问题，应在建议中提及

【维度说明】
- official: 官方回应（声明、通报、发布会）
- media: 媒体沟通（新闻稿、采访、合作）
- platform: 平台协调（置顶、标注、限流）
- user: 用户互动（评论、私信、FAQ）

输出严格 JSON 格式，字段名必须完全一致：
{{
  "summary": "综合建议摘要（不超过 80 字）",
  "actions": [
    {{
      "priority": "urgent|high|medium",
      "category": "official|media|platform|user",
      "action": "具体行动描述（必填，字段名必须是 action）",
      "timeline": "建议执行时间（如：立即、2小时内、24小时内）",
      "responsible": "责任方（如：公关部、法务部、运营部）"
    }}
  ]
}}
"""

    result = _call_llm_sync(prompt, "step4_suggestion")

    if result:
        summary = str(result.get("summary", ""))
        actions = []
        for item in result.get("actions", [])[:6]:
            action_text = (
                item.get("action")
                or item.get("coordinated_action")
                or item.get("action_item")
                or item.get("description")
                or ""
            )
            actions.append(
                ActionItem(
                    priority=str(item.get("priority", "medium")),
                    category=str(item.get("category", "official")),
                    action=str(action_text),
                    timeline=str(item.get("timeline", "")),
                    responsible=item.get("responsible"),
                )
            )
        suggestion_data = SuggestionData(summary=summary, actions=actions)
        _record_simulation_trace("step4_suggestion_output", {"suggestion": suggestion_data.model_dump(), "path": "llm"})
        return suggestion_data

    fallback = _fallback_suggestion(report, scenario)
    _record_simulation_trace("step4_suggestion_fallback", {"suggestion": fallback.model_dump(), "path": "rule"})
    return fallback


def _fallback_suggestion(report: ReportResponse | None, scenario: str = "general") -> SuggestionData:
    """建议生成规则兜底（场景差异化 + 多维度）"""
    risk_score = report.risk_score if report else 50

    actions: list[ActionItem] = []

    if risk_score >= 70:
        actions = [
            ActionItem(
                priority="urgent",
                category="official",
                action="发布带完整证据链的官方澄清声明",
                timeline="立即",
                responsible="公关部",
            ),
            ActionItem(
                priority="urgent",
                category="platform",
                action="联系平台置顶权威来源，申请谣言标注",
                timeline="1小时内",
                responsible="运营部",
            ),
            ActionItem(
                priority="high",
                category="user",
                action="开通评论区官方回复通道，发布 FAQ",
                timeline="2小时内",
                responsible="客服部",
            ),
            ActionItem(
                priority="high",
                category="media",
                action="准备新闻通稿，联系核心媒体跟进报道",
                timeline="4小时内",
                responsible="公关部",
            ),
        ]
        summary = "高风险舆情，需立即启动危机公关，优先官方澄清和平台协调。"
    elif risk_score >= 40:
        actions = [
            ActionItem(
                priority="high",
                category="official",
                action="准备澄清素材和补充说明",
                timeline="4小时内",
                responsible="公关部",
            ),
            ActionItem(
                priority="medium",
                category="platform",
                action="监测传播态势，必要时申请内容标注",
                timeline="持续",
                responsible="运营部",
            ),
            ActionItem(
                priority="medium",
                category="user",
                action="关注用户反馈，准备常见问题回复",
                timeline="24小时内",
                responsible="客服部",
            ),
        ]
        summary = "中等风险，建议主动准备应对素材，密切关注舆情走向。"
    else:
        actions = [
            ActionItem(
                priority="medium",
                category="official",
                action="持续监测舆情动态",
                timeline="每日",
                responsible="运营部",
            ),
            ActionItem(
                priority="medium",
                category="user",
                action="保持信息透明，及时回应用户疑问",
                timeline="按需",
                responsible="客服部",
            ),
        ]
        summary = "风险较低，建议持续监测并保持信息透明。"

    scenario_actions = _get_scenario_actions(scenario, risk_score)
    actions.extend(scenario_actions)

    return SuggestionData(summary=summary, actions=actions)


def _get_scenario_actions(scenario: str, risk_score: int) -> list[ActionItem]:
    """场景差异化行动建议"""
    scenario_map = {
        "health": ActionItem(
            priority="high" if risk_score >= 50 else "medium",
            category="official",
            action="联系专业机构或专家背书，增强权威性",
            timeline="24小时内",
            responsible="公关部",
        ),
        "governance": ActionItem(
            priority="high" if risk_score >= 50 else "medium",
            category="official",
            action="准备政策依据和官方文件引用",
            timeline="12小时内",
            responsible="法务部",
        ),
        "security": ActionItem(
            priority="high" if risk_score >= 50 else "medium",
            category="platform",
            action="评估信息泄露风险，必要时报警处理",
            timeline="立即",
            responsible="安全部",
        ),
        "technology": ActionItem(
            priority="medium",
            category="official",
            action="准备技术说明文档，邀请行业专家解读",
            timeline="24小时内",
            responsible="技术部",
        ),
        "finance": ActionItem(
            priority="high" if risk_score >= 50 else "medium",
            category="official",
            action="准备财务数据和监管合规证明",
            timeline="24小时内",
            responsible="财务部",
        ),
    }
    action = scenario_map.get(scenario)
    return [action] if action else []


def simulate_opinion_with_llm(
    text: str,
    claims: list[ClaimItem] | None = None,
    evidences: list[EvidenceItem] | None = None,
    report: ReportResponse | None = None,
    time_window_hours: int = 24,
    platform: str = "general",
    comments: list[str] | None = None,
) -> SimulateResponse:
    """
    完整的舆情预演流程（LLM 驱动 + 规则兜底）

    Args:
        text: 待传播文本
        claims: 已提取的主张列表
        evidences: 已检索的证据列表
        report: 已生成的风险报告
        time_window_hours: 预演时间窗口
        platform: 传播平台
        comments: 已有评论样本

    Returns:
        SimulateResponse: 完整的舆情预演结果
    """
    comments = comments or []

    _record_simulation_trace(
        "input",
        {
            "text": text[:500],
            "claims_count": len(claims) if claims else 0,
            "evidences_count": len(evidences) if evidences else 0,
            "report_risk_score": report.risk_score if report else None,
            "time_window_hours": time_window_hours,
            "platform": platform,
            "comments_count": len(comments),
            "llm_enabled": SIMULATION_LLM_ENABLED,
        },
    )

    context = _build_context_summary(text, claims, evidences, report)

    logger.info("[Simulation] Step 1: Emotion & Stance Analysis")
    emotion_result = _analyze_emotion_stance(text, claims, report, platform, comments)

    logger.info("[Simulation] Step 2: Narrative Generation")
    narratives = _generate_narratives(context, emotion_result, report, platform, time_window_hours)

    logger.info("[Simulation] Step 3: Flashpoint Identification")
    flashpoints, timeline = _identify_flashpoints(context, narratives, platform, time_window_hours)

    logger.info("[Simulation] Step 4: Suggestion Generation")
    suggestion = _generate_suggestion(context, emotion_result, narratives, flashpoints, report)

    result = SimulateResponse(
        emotion_distribution=emotion_result.get("emotion_distribution", {}),
        stance_distribution=emotion_result.get("stance_distribution", {}),
        narratives=narratives,
        flashpoints=flashpoints,
        suggestion=suggestion,
    )

    _record_simulation_trace(
        "output",
        {
            "emotion_distribution": result.emotion_distribution,
            "stance_distribution": result.stance_distribution,
            "narratives_count": len(result.narratives),
            "flashpoints_count": len(result.flashpoints),
            "suggestion": result.suggestion.model_dump(),
        },
    )

    return result


def simulate_opinion_stream(
    text: str,
    claims: list[ClaimItem] | None = None,
    evidences: list[EvidenceItem] | None = None,
    report: ReportResponse | None = None,
    time_window_hours: int = 24,
    platform: str = "general",
    comments: list[str] | None = None,
):
    """
    流式舆情预演 - 每完成一个阶段 yield 一次结果

    Yields:
        dict: 包含 stage 和对应阶段数据的字典
    """
    from app.schemas.detect import TimelineItem

    comments = comments or []

    _record_simulation_trace(
        "input_stream",
        {
            "text": text[:500],
            "claims_count": len(claims) if claims else 0,
            "evidences_count": len(evidences) if evidences else 0,
            "report_risk_score": report.risk_score if report else None,
            "time_window_hours": time_window_hours,
            "platform": platform,
            "comments_count": len(comments),
            "llm_enabled": SIMULATION_LLM_ENABLED,
        },
    )

    context = _build_context_summary(text, claims, evidences, report)

    accumulated: dict[str, Any] = {
        "emotion_distribution": {},
        "stance_distribution": {},
        "narratives": [],
        "flashpoints": [],
        "suggestion": {"summary": "", "actions": []},
        "timeline": [],
    }

    logger.info("[Simulation Stream] Step 1: Emotion & Stance Analysis")
    emotion_result = _analyze_emotion_stance(text, claims, report, platform, comments)
    accumulated["emotion_distribution"] = emotion_result.get("emotion_distribution", {})
    accumulated["stance_distribution"] = emotion_result.get("stance_distribution", {})
    accumulated["emotion_drivers"] = emotion_result.get("emotion_drivers", [])
    accumulated["stance_drivers"] = emotion_result.get("stance_drivers", [])
    logger.info("[Simulation Stream] Yielding emotion stage")
    yield {
        "stage": "emotion",
        "data": {
            "emotion_distribution": accumulated["emotion_distribution"],
            "stance_distribution": accumulated["stance_distribution"],
            "emotion_drivers": accumulated.get("emotion_drivers"),
            "stance_drivers": accumulated.get("stance_drivers"),
        },
    }

    logger.info("[Simulation Stream] Step 2: Narrative Generation")
    narratives = _generate_narratives(context, emotion_result, report, platform, time_window_hours)
    accumulated["narratives"] = [n.model_dump() for n in narratives]
    yield {
        "stage": "narratives",
        "data": {
            "narratives": accumulated["narratives"],
        },
    }

    logger.info("[Simulation Stream] Step 3: Flashpoint Identification")
    flashpoints, timeline = _identify_flashpoints(context, narratives, platform, time_window_hours)
    accumulated["flashpoints"] = flashpoints
    accumulated["timeline"] = [t.model_dump() if isinstance(t, TimelineItem) else t for t in timeline]
    yield {
        "stage": "flashpoints",
        "data": {
            "flashpoints": accumulated["flashpoints"],
            "timeline": accumulated["timeline"],
        },
    }

    logger.info("[Simulation Stream] Step 4: Suggestion Generation")
    suggestion = _generate_suggestion(context, emotion_result, narratives, flashpoints, report)
    accumulated["suggestion"] = suggestion.model_dump()
    yield {
        "stage": "suggestion",
        "data": {
            "suggestion": accumulated["suggestion"],
        },
    }

    _record_simulation_trace(
        "output_stream",
        {
            "emotion_distribution": accumulated["emotion_distribution"],
            "stance_distribution": accumulated["stance_distribution"],
            "narratives_count": len(accumulated["narratives"]),
            "flashpoints_count": len(accumulated["flashpoints"]),
            "suggestion": accumulated["suggestion"],
        },
    )
