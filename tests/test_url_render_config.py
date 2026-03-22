from pathlib import Path


def test_url_render_env_defaults_present() -> None:
    content = Path(".env.example").read_text(encoding="utf-8")
    assert "TRUTHCAST_URL_EXTRACT_RENDER_FALLBACK" in content
    assert "TRUTHCAST_URL_RENDER_TIMEOUT_SEC" in content
    assert "TRUTHCAST_URL_RENDER_WAIT_UNTIL" in content
