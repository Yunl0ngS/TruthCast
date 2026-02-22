import json
import os
import re
from datetime import datetime
from typing import Any
from urllib import error, request

from app.core.logger import get_logger
from app.schemas.detect import ClaimItem

logger = get_logger("truthcast.claim_extraction")


def extract_claims(text: str, max_claims: int | None = None) -> list[ClaimItem]:
    effective_max = max_claims or _claim_max_items()
    if _llm_enabled():
        method = os.getenv("TRUTHCAST_CLAIM_METHOD", "default").strip().lower()
        
        if method == "claimify":
            logger.info("Claim抽取：已启用 Claimify 模式 (Selection->Disambiguation->Decomposition)")
            claimify_claims = _extract_claims_with_claimify(text, max_items=effective_max)
            if claimify_claims:
                logger.info("Claim抽取：Claimify 模式抽取成功，claim数量=%s", len(claimify_claims))
                return claimify_claims
            logger.warning("Claim抽取：Claimify 模式抽取失败，已回退规则抽取")
        else:
            logger.info("Claim抽取：LLM模式已启用 (Default)，开始尝试LLM抽取")
            llm_claims = _extract_claims_with_llm(text, max_items=effective_max)
            if llm_claims:
                logger.info("Claim抽取：LLM抽取成功，claim数量=%s", len(llm_claims))
                return llm_claims
            logger.warning("Claim抽取：LLM抽取失败，已回退规则抽取")
    else:
        logger.info("Claim抽取：LLM模式未启用，使用规则抽取")

    claims = extract_claims_rule_based(text, max_claims=effective_max)
    logger.info("Claim抽取：规则抽取完成，claim数量=%s", len(claims))
    return claims


def extract_claims_rule_based(text: str, max_claims: int | None = None) -> list[ClaimItem]:
    effective_max = max_claims or _claim_max_items()
    parts = _split_sentences(text)
    raw_claims: list[ClaimItem] = []
    for idx, raw in enumerate(parts, start=1):
        sentence = raw.strip()
        if len(sentence) < 8 or _looks_like_non_verifiable(sentence):
            continue
        raw_claims.append(
            ClaimItem(
                claim_id=f"c{idx}",
                claim_text=sentence,
                entity=_normalize_entity(_extract_entity(sentence)),
                time=_normalize_time(_extract_time(sentence)),
                location=_normalize_location(_extract_location(sentence)),
                value=_normalize_value(_extract_value(sentence)),
                source_sentence=sentence,
            )
        )

    claims = _post_process_claims(raw_claims, max_items=effective_max)
    if claims:
        return claims

    text_clean = text.strip()
    return [
        ClaimItem(
            claim_id="c1",
            claim_text=text_clean,
            source_sentence=text_clean,
        )
    ]


def _llm_enabled() -> bool:
    return os.getenv("TRUTHCAST_LLM_ENABLED", "false").strip().lower() == "true"


def _extract_claims_with_llm(text: str, max_items: int | None = None) -> list[ClaimItem]:
    effective_max = max_items or _claim_max_items()
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("Claim抽取：TRUTHCAST_LLM_API_KEY为空，无法调用LLM")
        return []

    try:
        content = _call_llm(text, api_key=api_key, max_items=effective_max)
        parsed = _parse_llm_content(content)
        claims = _claims_from_json(parsed, max_items=effective_max)
        if not claims:
            logger.warning("Claim抽取：LLM返回为空或无有效claim")
        return claims
    except Exception as exc:
        logger.exception("Claim抽取：LLM调用异常，错误=%s", exc)
        return []


def _call_llm(text: str, api_key: str, max_items: int | None = None) -> str:
    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("TRUTHCAST_EXTRACTION_LLM_MODEL", "gpt-4o-mini")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    effective_max = max_items or _claim_max_items()
    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        "## 角色设定\n"
        "你是一个专业的核查分析师。任务是从提供的文本中抽取核心的“可核查事实主张 (Verifiable Claims)”。\n"
        f"当前参考日期：{current_date} (用于推断'昨天'、'上周'等相对时间)\n"
        "\n"
        "## 核心原则\n"
        "1. 原子化：将复合句拆解为独立事实。\n"
        "2. 指代消解：将“他/她/它”替换为具体实体名，确保Claim独立可读。\n"
        "3. 客观性：仅提取对客观世界的陈述，过滤主观评价、情绪宣泄和模糊推测。\n"
        "\n"
        "## 输出约束\n"
        "1. 格式：严格 JSON，无 Markdown，无注释。\n"
        "2. 结构：{\"claims\": [{\"claim_text\": \"...\", \"entity\": \"...\", \"time\": \"...\", \"location\": \"...\", \"value\": \"...\", \"source_sentence\": \"...\"}]}\n"
        f"3. 数量：Top-{effective_max} 条最有核查价值的主张。\n"
        "4. 字段规范：\n"
        "   - time: 格式 YYYY-MM-DD，无法推断则留空。\n"
        "   - value: 仅提取关键数值/百分比。\n"
        "\n"
        "## 示例 (Few-Shot)\n"
        "输入：震惊！昨天马斯克在X平台宣布SpaceX濒临破产，股价暴跌20%。这太可怕了，大家赶紧转！（假设昨天是2026-02-09）\n"
        "输出：\n"
        '{"claims": ['
        '{"claim_text": "马斯克于2026-02-09宣布SpaceX濒临破产", "entity": "马斯克", "time": "2026-02-09", "location": "X平台", "value": "", "source_sentence": "马斯克在X平台宣布SpaceX濒临破产"},'
        '{"claim_text": "SpaceX股价暴跌20%", "entity": "SpaceX", "time": "2026-02-09", "location": "", "value": "20%", "source_sentence": "股价暴跌20%"}'
        ']}'
        "\n"
        "## 负例 (忽略)\n"
        "- “我觉得这事有点蹊跷”（无事实）\n"
        "- “转发保平安”（纯情绪）\n"
    )

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是信息抽取引擎，只返回严格JSON。"},
            {"role": "user", "content": f"{prompt}\n\n待处理文本：\n{text}"},
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    
    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "60"))
    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
    except error.URLError as exc:
        raise RuntimeError(f"LLM请求失败: {exc}") from exc

    body = json.loads(raw)
    return body["choices"][0]["message"]["content"]


def _extract_claims_with_claimify(text: str, max_items: int | None = None) -> list[ClaimItem]:
    effective_max = max_items or _claim_max_items()
    api_key = os.getenv("TRUTHCAST_LLM_API_KEY", "").strip()
    if not api_key:
        logger.warning("Claim抽取(Claimify)：TRUTHCAST_LLM_API_KEY为空，无法调用LLM")
        return []

    try:
        # Step 1: Selection & Disambiguation
        logger.info("Claimify Step 1: 筛选与消歧...")
        step1_json = _call_claimify_step1(text, api_key)
        refined_sentences = _parse_llm_content(step1_json).get("sentences", [])
        
        if not refined_sentences:
            logger.warning("Claimify Step 1: 未提取到有效句子")
            return []
            
        logger.info(f"Claimify Step 1: 提取到 {len(refined_sentences)} 个核心句子")

        # Step 2: Decomposition & Atomization
        logger.info("Claimify Step 2: 原子化拆解与字段提取...")
        step2_json = _call_claimify_step2(refined_sentences, api_key)
        all_raw_claims = _parse_llm_content(step2_json).get("claims", [])
        
        if not all_raw_claims:
            logger.warning("Claimify Step 2: 未提取到有效主张")
            return []

        # Step 3: Ranking & Filtering
        # (Only enabling Step 3 if we have enough candidates)
        if len(all_raw_claims) > 1:
            logger.info(f"Claimify Step 3: 对 {len(all_raw_claims)} 条候选主张进行价值重排序...")
            step3_json = _call_claimify_step3(all_raw_claims, max_items=effective_max, api_key=api_key)
            final_claims_data = _parse_llm_content(step3_json)
        else:
            logger.info("候选主张较少，跳过 Step 3 重排序")
            final_claims_data = {"claims": all_raw_claims}

        claims = _claims_from_json(final_claims_data, max_items=effective_max)
        if not claims:
            logger.warning("Claimify 最终结果为空")
        return claims
    except Exception as exc:
        logger.exception("Claim抽取(Claimify)：LLM调用异常，错误=%s", exc)
        return []


def _call_llm_generic(system_prompt: str, user_content: str, api_key: str, temp: float = 0.1) -> str:
    base_url = os.getenv("TRUTHCAST_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.getenv("TRUTHCAST_EXTRACTION_LLM_MODEL", "gpt-4o-mini")
    endpoint = base_url.rstrip("/") + "/chat/completions"
    
    payload = {
        "model": model,
        "temperature": temp,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    # Use timeout per request
    timeout_val = float(os.getenv("TRUTHCAST_LLM_TIMEOUT", "60"))
    try:
        with request.urlopen(req, timeout=timeout_val) as resp:
            raw = resp.read().decode("utf-8")
        body = json.loads(raw)
        result = body["choices"][0]["message"]["content"]
        
        # Debug Logging
        _record_llm_trace(system_prompt, user_content, result)
        
        return result
    except Exception as exc:
        raise RuntimeError(f"LLM请求失败: {exc}") from exc


def _record_llm_trace(system_prompt: str, user_content: str, result: str) -> None:
    """记录 LLM 调用日志到 debug 目录"""
    if os.getenv("TRUTHCAST_DEBUG_LLM", "true").lower() != "true":
        return

    try:
        # Calculate strict project root: D:\Project\TruthCast
        # app/services/claim_extraction.py -> ../../..
        current_file = os.path.abspath(__file__)
        services_dir = os.path.dirname(current_file)
        app_dir = os.path.dirname(services_dir)
        project_root = os.path.dirname(app_dir)
        
        debug_dir = os.path.join(project_root, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        trace_file = os.path.join(debug_dir, "claimify_trace.jsonl")
        
        # Identify step from prompt
        step = "unknown"
        if "Claimify 预处理专家" in system_prompt:
            step = "step1_selection"
        elif "Claimify 事实抽取专家" in system_prompt:
            step = "step2_extraction"
        elif "Claimify 价值评估专家" in system_prompt:
            step = "step3_ranking"

        entry = {
            "timestamp": datetime.now().isoformat(),
            "step": step,
            "system_prompt": system_prompt,
            "user_content": user_content,
            "output_result": result
        }
        
        with open(trace_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    except Exception as e:
        # Log error to console instead of silent fail
        print(f"[ERROR] Debug trace failed: {e}")
        logger.error(f"Debug trace failed: {e}")


def _call_claimify_step1(text: str, api_key: str) -> str:
    """Step 1: Selection (筛选) + Disambiguation (消歧)"""
    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = (
        "## 角色：Claimify 预处理专家\n"
        "任务：对输入文本进行【筛选】和【消歧】，输出独立的、包含可核查事实的句子列表。\n"
        f"参考日期：{current_date}\n"
        "\n"
        "## 处理规则\n"
        "1. **筛选 (Selection)**：\n"
        "   - **保留**：具体的事件、数据、声明、行为描述。\n"
        "   - **丢弃**：\n"
        "     - 纯粹的个人观点或情绪 (如“我觉得这很荒谬”)。\n"
        "     - 模糊的未来预测 (如“未来可能会更好”)。\n"
        "     - 无事实信息的元数据 (如“点击链接了解更多”、“图片来源：某某”、“本研究发表在...杂志”)。\n"
        "2. **消歧 (Disambiguation)**：\n"
        "   - 将代词 (他/她/它/这) 替换为文中指代的具体实体。\n"
        "   - 将相对时间 (昨天/上周) 转换为基于参考日期的具体描述 (如“在202x年x月x日”)。\n"
        "   - 如果一句话指代不清且无法通过上下文复原，直接**丢弃**。\n"
        "\n"
        "## 输出格式\n"
        "严格 JSON: `{\"sentences\": [\"重写后的句子1\", \"重写后的句子2\"]}`"
    )
    
    return _call_llm_generic(prompt, f"待处理文本：\n{text}", api_key, temp=0.1)


def _call_claimify_step2(sentences: list[str], api_key: str) -> str:
    """Step 2: Decomposition (原子化) + Initial Extraction (初步提取) - 不限量"""
    # 移除 max_items 限制，尽可能多提
    sentences_text = json.dumps(sentences, ensure_ascii=False, indent=2)
    
    prompt = (
        "## 角色：Claimify 事实抽取专家\n"
        "任务：将给定的句子列表拆解为原子化的【可核查事实主张 (Verifiable Claims)】。\n"
        "\n"
        "## 处理规则\n"
        "1. **拆解 (Decomposition)**：\n"
        "   - 如果通过 Step 1 传入的句子包含多个独立事实，请拆分为多条 Claim。\n"
        "   - 确保每条 Claim 是独立的、可被验证真伪的陈述。\n"
        "2. **字段提取**：\n"
        "   - `claim_text`: 最终的最简事实陈述。\n"
        "   - `source_sentence`: 对应的那句输入文本。\n"
        "   - `entity`: 关键实体（人名/组织/物品）。\n"
        "   - `time`: YYYY-MM-DD (若无明确时间则留空)。\n"
        "   - `value`: 包含的关键数值或百分比。\n"
        # "3. **数量控制**：**尽可能完整提取**，不要遗漏任何有价值的事实。后续步骤会进行筛选。\n"
        "\n"
        "## 输出格式\n"
        "严格 JSON: `{\"claims\": [{\"claim_text\": \"...\", \"entity\": \"...\", \"time\": \"...\", \"value\": \"...\", \"source_sentence\": \"...\"}]}`"
    )

    return _call_llm_generic(prompt, f"待处理句子列表：\n{sentences_text}", api_key, temp=0.1)


def _call_claimify_step3(candidates: list[dict[str, Any]], max_items: int | None = None, api_key: str = "") -> str:
    """Step 3: Ranking & Filtering (去重、合并与价值排序)"""
    effective_max = max_items or _claim_max_items()
    # 仅传递必要的字段以节省 Token
    simplified_candidates = [
        {"id": i, "claim": c.get("claim_text", "")}
        for i, c in enumerate(candidates)
    ]
    candidates_text = json.dumps(simplified_candidates, ensure_ascii=False, indent=2)
    
    prompt = (
        "## 角色：Claimify 价值评估专家\n"
        "任务：对候选主张列表进行【去重合并】与【价值排序】，输出 Top-N 条最具核查价值的主张。\n"
        "\n"
        "## 处理流程\n"
        "1. **去重与合并 (Deduplicate & Merge)**：\n"
        "   - 若多条主张语义高度重复（如“股价大跌”与“股票下跌”），请合并为一条更完整、准确的主张。\n"
        "   - 若某条主张被包含在另一条更详细的主张中，仅保留详细版。\n"
        "2. **价值评估 (Check-worthiness)**：\n"
        "   - 优先保留：包含具体数据/时间/实体、对事件核心叙事有重大影响的主张。\n"
        "   - 降权/丢弃：主观评价、模糊预测、无关背景、元数据（如来源说明）。\n"
        "\n"
        "## 输出要求\n"
        f"1. 输出最终经过合并与筛选的 **Top-{effective_max}** 条主张。\n"
        "2. 对于合并后的主张，`source_indices` 记录其来源的原始ID列表。\n"
        "3. 格式：严格 JSON: `{\"claims\": [{\"claim_text\": \"合并后的主张...\", \"source_indices\": [0, 2]}]}`"
    )
    
    response = _call_llm_generic(prompt, f"候选列表：\n{candidates_text}", api_key, temp=0.1)
    
    try:
        parsed = _parse_llm_content(response)
        merged_claims_data = parsed.get("claims", [])
        
        final_claims = []
        for item in merged_claims_data:
            text = item.get("claim_text")
            indices = item.get("source_indices", [])
            
            # 尝试回溯原始信息以丰富字段 (entity/time/etc)
            # 我们用第一个来源的元数据作为基础，但使用新的合并文本
            base_candidate = {}
            if indices and isinstance(indices, list):
                # 找到第一个有效的原始索引
                first_idx = next((i for i in indices if isinstance(i, int) and 0 <= i < len(candidates)), None)
                if first_idx is not None:
                    base_candidate = candidates[first_idx].copy()
            
            # 构建新对象
            new_claim = base_candidate if base_candidate else {}
            new_claim["claim_text"] = text  # 使用合并后的文本
            # 主动清理掉旧的 value/entity 字段，因为合并后可能变了，让后续 _claims_from_json 里的逻辑重新提取
            # 但 time/location 这种上下文信息通常不变，可以保留作为兜底
            
            final_claims.append(new_claim)
        
        # Fallback: if empty, return original top N
        if not final_claims and candidates:
             return json.dumps({"claims": candidates[:effective_max]})
             
        return json.dumps({"claims": final_claims})
    except Exception:
        # Fallback on parse error
        return json.dumps({"claims": candidates[:effective_max]})


def _call_claimify_step3_by_ids(candidates: list[dict[str, Any]], max_items: int, api_key: str) -> str:
    # Deprecated: Merged logic into _call_claimify_step3 for simplicity and correct context
    return "{}"




def _parse_llm_content(content: str) -> dict[str, Any]:
    from app.services.json_utils import safe_json_loads
    
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
    
    result = safe_json_loads(cleaned, "claim_extraction")
    if result is None:
        logger.error("Claim抽取：JSON解析完全失败，返回空结果")
        return {"claims": []}
    return result


def _claims_from_json(payload: dict[str, Any], max_items: int | None = None) -> list[ClaimItem]:
    effective_max = max_items or _claim_max_items()
    rows = payload.get("claims", [])
    claims: list[ClaimItem] = []
    for idx, row in enumerate(rows, start=1):
        if isinstance(row, str):
            # 兼容 LLM 返回字符串列表的情况
            claim_text = _normalize_claim_text(row)
            source_sentence = claim_text
            entity_val = _extract_entity(source_sentence)
            time_val = _extract_time(source_sentence)
            location_val = _extract_location(source_sentence)
            value_val = _extract_value(source_sentence)
        else:
            # 标准字典结构
            claim_text = _normalize_claim_text(row.get("claim_text"))
            # 如果没有 source_sentence，暂用 claim_text 兜底，后续流程会进一步处理
            source_sentence = str(row.get("source_sentence", claim_text)).strip()
            
            # 优先用 LLM 提取的字段，否则规则回退
            entity_val = row.get("entity") or _extract_entity(source_sentence)
            time_val = row.get("time") or _extract_time(source_sentence)
            location_val = row.get("location") or _extract_location(source_sentence)
            value_val = row.get("value") or _extract_value(source_sentence)

        if not claim_text or _looks_like_non_verifiable(claim_text):
            continue
        claims.append(
            ClaimItem(
                claim_id=f"c{idx}",
                claim_text=claim_text,
                entity=_normalize_entity(entity_val),
                time=_normalize_time(time_val),
                location=_normalize_location(location_val),
                value=_normalize_value(value_val),
                source_sentence=source_sentence or claim_text,
            )
        )
    return _post_process_claims(claims)


def _post_process_claims(claims: list[ClaimItem], max_items: int | None = None) -> list[ClaimItem]:
    effective_max = max_items or _claim_max_items()
    if not claims:
        return []

    # Keep verifiable and risky claims first, then cap by Top-N.
    scored: list[tuple[float, ClaimItem]] = []
    for claim in claims:
        score = _claim_score(claim)
        if score >= _claim_min_score():
            scored.append((score, claim))

    if not scored:
        scored = [(_claim_score(claim), claim) for claim in claims]

    scored.sort(key=lambda row: row[0], reverse=True)
    ranked = [row[1] for row in scored]
    deduped = _dedupe_and_reindex(ranked)
    return deduped[:effective_max]


def _claim_score(claim: ClaimItem) -> float:
    score = 0.0
    if claim.entity:
        score += 0.25
    if claim.time:
        score += 0.25
    if claim.value:
        score += 0.25
    if claim.location:
        score += 0.1
    if _contains_risk_terms(claim.claim_text):
        score += 0.15
    if len(claim.claim_text) > 120:
        score -= 0.08
    return round(max(0.0, min(1.0, score)), 4)


def _contains_risk_terms(text: str) -> bool:
    lowered = text.lower()
    terms = [
        "震惊",
        "内部消息",
        "必须转发",
        "100%",
        "包治百病",
        "shocking",
        "internal source",
        "must share",
    ]
    return any(term in lowered or term in text for term in terms)


def _claim_max_items() -> int:
    raw = os.getenv("TRUTHCAST_CLAIM_MAX_ITEMS", "8").strip()
    try:
        value = int(raw)
    except ValueError:
        return 8
    return max(1, min(20, value))


def _claim_min_score() -> float:
    raw = os.getenv("TRUTHCAST_CLAIM_MIN_SCORE", "0.25").strip()
    try:
        value = float(raw)
    except ValueError:
        return 0.25
    return max(0.0, min(1.0, value))


def _split_sentences(text: str) -> list[str]:
    return [part for part in re.split(r"[。！？!?;；\n]+", text) if part.strip()]


def _none_if_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_claim_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:220]


def _normalize_entity(value: Any) -> str | None:
    text = _none_if_empty(value)
    if not text:
        return None
    return re.sub(r"\s+", " ", text)[:80]


def _normalize_location(value: Any) -> str | None:
    text = _none_if_empty(value)
    if not text:
        return None
    return re.sub(r"\s+", " ", text)[:80]


def _normalize_value(value: Any) -> str | None:
    text = _none_if_empty(value)
    if not text:
        return None
    match = re.search(r"\b\d+(\.\d+)?%|\b\d+(\.\d+)?\b", text)
    return match.group(0) if match else None


def _normalize_time(value: Any) -> str | None:
    text = _none_if_empty(value)
    if not text:
        return None
    text = text.replace("/", "-")
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _extract_time(text: str) -> str | None:
    match = re.search(r"\b(20\d{2}[-/]\d{1,2}[-/]\d{1,2})\b", text)
    return match.group(1) if match else None


def _extract_value(text: str) -> str | None:
    match = re.search(r"\b\d+(\.\d+)?%|\b\d+(\.\d+)?\b", text)
    return match.group(0) if match else None


def _extract_entity(text: str) -> str | None:
    m = re.search(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text)
    if m:
        return m.group(1)
    m = re.search(r"([\u4e00-\u9fa5]{2,12})(?:表示|称|发布|通报|指出)", text)
    if m:
        return m.group(1)
    return None


def _extract_location(text: str) -> str | None:
    m = re.search(r"\b(in|at)\s+([A-Za-z][A-Za-z\- ]{1,40})\b", text, flags=re.IGNORECASE)
    if m:
        return m.group(2).strip()
    m = re.search(r"在([\u4e00-\u9fa5]{2,12})", text)
    if m:
        return m.group(1)
    return None


def _looks_like_non_verifiable(text: str) -> bool:
    lowered = text.lower()
    opinion_terms = ["i think", "maybe", "perhaps", "感觉", "我觉得", "可能吧", "太离谱了"]
    if any(term in lowered for term in opinion_terms):
        if not re.search(r"\b\d+(\.\d+)?%?\b", text) and not _extract_time(text):
            return True
    return False


def _dedupe_and_reindex(claims: list[ClaimItem]) -> list[ClaimItem]:
    seen: set[str] = set()
    cleaned: list[ClaimItem] = []
    for claim in claims:
        key = re.sub(r"[^a-z0-9\u4e00-\u9fa5]+", "", claim.claim_text.lower())
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(claim)

    for idx, claim in enumerate(cleaned, start=1):
        claim.claim_id = f"c{idx}"
    return cleaned
