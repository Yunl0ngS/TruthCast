import json
import os
from dataclasses import dataclass
from typing import Sequence
from urllib import error, request

from app.core.logger import get_logger
from app.services.json_utils import safe_json_loads
from app.services.url_extraction.extractors import ContentCandidate

logger = get_logger("truthcast.url_extraction.llm_postprocess")


@dataclass
class LLMExtractionResult:
    title: str
    content: str
    publish_date: str


def _llm_enabled() -> bool:
    return (os.getenv("TRUTHCAST_URL_EXTRACT_LLM_ENABLED", "false") or "false").strip().lower() == "true"


def _llm_mode() -> str:
    return (os.getenv("TRUTHCAST_URL_EXTRACT_LLM_MODE", "postprocess") or "postprocess").strip().lower()


def _llm_model() -> str:
    return (os.getenv("TRUTHCAST_URL_EXTRACT_LLM_MODEL") or os.getenv("TRUTHCAST_LLM_MODEL") or "gpt-4o-mini").strip()


def _llm_timeout() -> float:
    try:
        return float(os.getenv("TRUTHCAST_URL_EXTRACT_LLM_TIMEOUT_SEC", "20"))
    except (TypeError, ValueError):
        return 20.0


def _api_key() -> str:
    return (os.getenv("TRUTHCAST_LLM_API_KEY") or "").strip()


def _base_url() -> str:
    return (os.getenv("TRUTHCAST_LLM_BASE_URL") or "https://api.openai.com/v1").rstrip("/")


def _call_llm(system_prompt: str, user_prompt: str) -> LLMExtractionResult | None:
    if not _llm_enabled():
        return None
    api_key = _api_key()
    if not api_key:
        logger.info("URL抽取LLM：未配置 API Key，跳过")
        return None

    payload = {
        "model": _llm_model(),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{_base_url()}/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=_llm_timeout()) as resp:
            raw = resp.read().decode("utf-8")
    except (error.URLError, TimeoutError, RuntimeError) as exc:
        logger.warning("URL抽取LLM：请求失败 error=%s", exc)
        return None

    body = json.loads(raw)
    content = body["choices"][0]["message"]["content"]
    parsed = safe_json_loads(content, "url_extraction_llm")
    if not parsed:
        return None
    return LLMExtractionResult(
        title=str(parsed.get("title", "")).strip(),
        content=str(parsed.get("content", "")).strip(),
        publish_date=str(parsed.get("publish_date", "")).strip(),
    )


def postprocess_extracted_content(
    title: str,
    content: str,
    publish_date: str,
    source_url: str,
) -> LLMExtractionResult | None:
    mode = _llm_mode()
    if mode not in {"postprocess", "both"}:
        return None
    system_prompt = (
        "你是新闻正文清洗助手。"
        "只根据已抽取的标题、正文、日期做轻量清洗，去掉推荐阅读、责任编辑、免责声明等尾部噪声。"
        "不要补造不存在的事实，只返回 JSON。"
    )
    user_prompt = (
        f"来源链接: {source_url}\n"
        f"标题: {title}\n"
        f"发布日期: {publish_date}\n"
        f"正文:\n{content}\n\n"
        "返回 {\"title\":\"...\",\"content\":\"...\",\"publish_date\":\"...\"}"
    )
    return _call_llm(system_prompt, user_prompt)


def rescue_extracted_candidates(
    title: str,
    publish_date: str,
    source_url: str,
    candidates: Sequence[ContentCandidate],
) -> LLMExtractionResult | None:
    mode = _llm_mode()
    if mode not in {"rescue", "both"}:
        return None
    if not candidates:
        return None
    candidate_lines = []
    for idx, item in enumerate(candidates, start=1):
        candidate_lines.append(
            f"[候选{idx}] extractor={item.extractor_name} title={item.title} content={item.content}"
        )
    system_prompt = (
        "你是新闻正文兜底整理助手。"
        "你只能基于提供的候选正文做整理，不能读取原始 HTML，也不能编造事实。"
        "从候选中选出最像主体新闻的一版并返回 JSON。"
    )
    user_prompt = (
        f"来源链接: {source_url}\n"
        f"标题提示: {title}\n"
        f"发布日期提示: {publish_date}\n"
        f"候选正文:\n" + "\n".join(candidate_lines) + "\n\n"
        "返回 {\"title\":\"...\",\"content\":\"...\",\"publish_date\":\"...\"}"
    )
    return _call_llm(system_prompt, user_prompt)
