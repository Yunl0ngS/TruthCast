import json
import logging
from typing import Any

logger = logging.getLogger("truthcast.json_utils")

try:
    from json_repair import repair_json
    HAS_JSON_REPAIR = True
except ImportError:
    HAS_JSON_REPAIR = False
    logger.warning("json-repair not installed, JSON auto-repair disabled")


def serialize_for_json(obj: Any) -> Any:
    """
    Recursively convert objects to JSON-serializable types.
    Handles Pydantic models, dicts, lists, and primitive types.
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "model_dump"):
        return serialize_for_json(obj.model_dump())
    if hasattr(obj, "dict"):
        return serialize_for_json(obj.dict())
    if isinstance(obj, dict):
        return {k: serialize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_for_json(item) for item in obj]
    return str(obj)


def safe_json_loads(content: str, context: str = "") -> dict[str, Any] | None:
    """
    Safely parse JSON with auto-repair fallback.
    
    Args:
        content: JSON string to parse
        context: Context description for logging (e.g., "claim_extraction")
    
    Returns:
        Parsed dict or None if parsing fails
    """
    content = content.strip()
    
    # First try: direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        logger.debug("%s: Direct JSON parse failed: %s", context, e)
    
    # Second try: with json-repair
    if HAS_JSON_REPAIR:
        try:
            repaired = repair_json(content)
            result = json.loads(repaired)
            logger.info("%s: JSON auto-repair succeeded", context)
            return result
        except Exception as e:
            logger.warning("%s: JSON auto-repair failed: %s", context, e)
    
    # Third try: clean common issues manually
    try:
        cleaned = _clean_json_content(content)
        result = json.loads(cleaned)
        logger.info("%s: JSON manual clean succeeded", context)
        return result
    except json.JSONDecodeError as e:
        logger.error("%s: All JSON parse attempts failed: %s", context, e)
        return None


def _clean_json_content(content: str) -> str:
    """Attempt to clean common JSON issues."""
    import re
    
    result = content
    
    # Remove trailing commas before } or ]
    result = re.sub(r',\s*([}\]])', r'\1', result)
    
    # Remove single-line comments
    result = re.sub(r'//.*$', '', result, flags=re.MULTILINE)
    
    # Remove multi-line comments
    result = re.sub(r'/\*.*?\*/', '', result, flags=re.DOTALL)
    
    # Fix Chinese quotes
    result = result.replace('"', '"').replace('"', '"')
    result = result.replace(''', "'").replace(''', "'")
    
    # Fix control characters (newlines, tabs in strings)
    result = re.sub(r'[\x00-\x1f\x7f-\x9f](?![^"]*"[^"]*(?:"[^"]*"[^"]*)*$)', '', result)
    
    # Try to extract JSON object if surrounded by other text
    json_match = re.search(r'\{[\s\S]*\}', result)
    if json_match:
        result = json_match.group(0)
    
    return result
