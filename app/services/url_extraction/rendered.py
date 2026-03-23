import os
from dataclasses import dataclass

from playwright.sync_api import sync_playwright


@dataclass
class RenderedPage:
    final_url: str
    html: str
    success: bool
    error_msg: str = ""


def _render_timeout_ms() -> int:
    try:
        return max(1000, int(float(os.getenv("TRUTHCAST_URL_RENDER_TIMEOUT_SEC", "20")) * 1000))
    except (TypeError, ValueError):
        return 20000


def _render_wait_until() -> str:
    value = (os.getenv("TRUTHCAST_URL_RENDER_WAIT_UNTIL", "networkidle") or "networkidle").strip()
    return value if value in {"load", "domcontentloaded", "networkidle"} else "networkidle"


def render_page(url: str) -> RenderedPage:
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until=_render_wait_until(), timeout=_render_timeout_ms())
                return RenderedPage(final_url=page.url, html=page.content(), success=True)
            finally:
                browser.close()
    except Exception as exc:
        return RenderedPage(final_url=url, html="", success=False, error_msg=str(exc))
