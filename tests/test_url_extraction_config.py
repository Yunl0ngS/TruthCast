from pathlib import Path


def test_url_extract_env_defaults_present() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")
    assert "TRUTHCAST_URL_EXTRACT_ENABLED" in content
    assert "TRUTHCAST_URL_EXTRACT_PRIMARY" in content
    assert "TRUTHCAST_URL_EXTRACT_SECONDARY" in content
    assert "TRUTHCAST_URL_EXTRACT_MIN_CONTENT_LEN" in content
    assert "TRUTHCAST_URL_EXTRACT_MIN_PARAGRAPHS" in content
    assert "TRUTHCAST_URL_EXTRACT_MAX_LINK_DENSITY" in content
