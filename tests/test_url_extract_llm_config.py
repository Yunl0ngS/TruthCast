from pathlib import Path


def test_url_extract_llm_env_defaults_present() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")
    assert "TRUTHCAST_URL_EXTRACT_LLM_ENABLED" in content
    assert "TRUTHCAST_URL_EXTRACT_LLM_MODE" in content
    assert "TRUTHCAST_URL_EXTRACT_LLM_MODEL" in content
    assert "TRUTHCAST_URL_EXTRACT_LLM_TIMEOUT_SEC" in content
