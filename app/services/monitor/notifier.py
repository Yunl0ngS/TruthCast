from __future__ import annotations

import copy
import smtplib
from abc import ABC, abstractmethod
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import httpx

from app.schemas.monitor import NotifyChannel


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in incoming.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class NotificationChannel(ABC):
    @abstractmethod
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        raise NotImplementedError


class WebhookChannel(NotificationChannel):
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        url = str(config.get("url", "")).strip()
        if not url:
            return {"success": False, "message": "missing webhook url"}

        method = str(config.get("method", "POST")).upper()
        headers = config.get("headers", {})
        payload = self._build_payload(alert, config.get("template"))

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, url, json=payload, headers=headers)
        body = response.json() if hasattr(response, "json") else {}
        return {
            "success": 200 <= response.status_code < 300,
            "message": f"HTTP {response.status_code}",
            "response": body,
        }

    def _build_payload(self, alert, template: dict[str, Any] | None):  # noqa: ANN001
        if template:
            payload = copy.deepcopy(template)
            payload.setdefault("alert", alert.model_dump(mode="json"))
            return payload
        return alert.model_dump(mode="json")


class WecomChannel(NotificationChannel):
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        webhook_url = str(config.get("webhook_url", "")).strip()
        if not webhook_url:
            return {"success": False, "message": "missing wecom webhook_url"}
        mentioned_list = config.get("mentioned_list", [])
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": self._format_markdown(alert, mentioned_list)},
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
        return {
            "success": 200 <= response.status_code < 300,
            "message": f"HTTP {response.status_code}",
            "response": response.json() if hasattr(response, "json") else {},
        }

    def _format_markdown(self, alert, mentioned_list: list[str]) -> str:  # noqa: ANN001
        lines = [
            "## 舆情预警",
            f"**标题**: {alert.hot_item_title}",
            f"**平台**: {alert.hot_item_platform}",
            f"**风险等级**: {alert.risk_level} ({alert.risk_score}分)",
            f"**热度排名**: 第 {alert.hot_item_rank} 名",
            f"**触发原因**: {alert.trigger_reason}",
            f"[查看详情]({alert.hot_item_url})",
        ]
        if mentioned_list:
            lines.append(f"<@{'><@'.join(mentioned_list)}>")
        return "\n".join(lines)


class DingtalkChannel(NotificationChannel):
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        webhook_url = str(config.get("webhook_url", "")).strip()
        if not webhook_url:
            return {"success": False, "message": "missing dingtalk webhook_url"}
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"舆情预警: {alert.hot_item_title[:20]}",
                "text": self._format_markdown(alert),
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
        return {
            "success": 200 <= response.status_code < 300,
            "message": f"HTTP {response.status_code}",
            "response": response.json() if hasattr(response, "json") else {},
        }

    def _format_markdown(self, alert) -> str:  # noqa: ANN001
        return "\n".join(
            [
                f"### {alert.hot_item_title}",
                f"- 平台: {alert.hot_item_platform}",
                f"- 风险: {alert.risk_level} / {alert.risk_score}",
                f"- 触发: {alert.trigger_reason}",
                f"- 链接: {alert.hot_item_url}",
            ]
        )


class FeishuChannel(NotificationChannel):
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        webhook_url = str(config.get("webhook_url", "")).strip()
        if not webhook_url:
            return {"success": False, "message": "missing feishu webhook_url"}
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": "舆情预警"},
                    "template": self._get_color(alert.risk_level),
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": self._format_content(alert)},
                    }
                ],
            },
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
        return {
            "success": 200 <= response.status_code < 300,
            "message": f"HTTP {response.status_code}",
            "response": response.json() if hasattr(response, "json") else {},
        }

    def _get_color(self, risk_level: str) -> str:
        if risk_level in {"high_risk", "likely_misinformation"}:
            return "red"
        if risk_level in {"suspicious", "needs_context"}:
            return "orange"
        return "blue"

    def _format_content(self, alert) -> str:  # noqa: ANN001
        return "\n".join(
            [
                f"**标题**: {alert.hot_item_title}",
                f"**平台**: {alert.hot_item_platform}",
                f"**风险**: {alert.risk_level} ({alert.risk_score})",
                f"**触发原因**: {alert.trigger_reason}",
            ]
        )


class EmailChannel(NotificationChannel):
    async def send(self, alert, config: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN001
        smtp_host = str(config.get("smtp_host", "")).strip()
        from_addr = str(config.get("from_addr", "")).strip()
        to_addrs = config.get("to_addrs", [])
        if not smtp_host or not from_addr or not to_addrs:
            return {"success": False, "message": "missing email config"}

        smtp_port = int(config.get("smtp_port", 587))
        smtp_user = config.get("smtp_user")
        smtp_password = config.get("smtp_password")

        message = MIMEMultipart("alternative")
        message["Subject"] = f"[舆情预警] {alert.hot_item_title[:50]}"
        message["From"] = from_addr
        message["To"] = ", ".join(to_addrs)
        text_content = self._format_text(alert)
        html_content = self._format_html(alert)
        message.attach(MIMEText(text_content, "plain", "utf-8"))
        message.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(from_addr, to_addrs, message.as_string())
            return {"success": True, "message": "Email sent"}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "message": str(exc)}

    def _format_text(self, alert) -> str:  # noqa: ANN001
        return "\n".join(
            [
                "舆情预警",
                f"标题: {alert.hot_item_title}",
                f"平台: {alert.hot_item_platform}",
                f"风险: {alert.risk_level} ({alert.risk_score})",
                f"触发原因: {alert.trigger_reason}",
                f"链接: {alert.hot_item_url}",
            ]
        )

    def _format_html(self, alert) -> str:  # noqa: ANN001
        return (
            "<html><body>"
            f"<h2>舆情预警</h2><p><strong>标题</strong>: {alert.hot_item_title}</p>"
            f"<p><strong>平台</strong>: {alert.hot_item_platform}</p>"
            f"<p><strong>风险</strong>: {alert.risk_level} ({alert.risk_score})</p>"
            f"<p><strong>触发原因</strong>: {alert.trigger_reason}</p>"
            f"<p><a href=\"{alert.hot_item_url}\">查看详情</a></p>"
            "</body></html>"
        )


class NotifierService:
    def __init__(self):
        self.channels: dict[NotifyChannel, NotificationChannel] = {
            NotifyChannel.WEBHOOK: WebhookChannel(),
            NotifyChannel.WECOM: WecomChannel(),
            NotifyChannel.DINGTALK: DingtalkChannel(),
            NotifyChannel.FEISHU: FeishuChannel(),
            NotifyChannel.EMAIL: EmailChannel(),
        }

    async def send(self, alert, subscriptions) -> list[dict]:  # noqa: ANN001
        if not alert.notify_channels:
            return []

        results = []
        for channel_type in alert.notify_channels:
            resolved = channel_type if isinstance(channel_type, NotifyChannel) else NotifyChannel(channel_type)
            channel = self.channels.get(resolved)
            if channel is None:
                results.append(
                    {
                        "channel": resolved.value,
                        "success": False,
                        "message": "Unknown channel type",
                    }
                )
                continue

            config = self._merge_channel_config(resolved, subscriptions)
            try:
                result = await channel.send(alert, config)
            except Exception as exc:  # noqa: BLE001
                result = {"success": False, "message": str(exc)}
            result["channel"] = resolved.value
            results.append(result)
        return results

    def _merge_channel_config(self, channel_type: NotifyChannel, subscriptions) -> dict[str, Any]:  # noqa: ANN001
        merged: dict[str, Any] = {}
        key = channel_type.value
        for subscription in subscriptions:
            notify_config = getattr(subscription, "notify_config", {}) or {}
            channel_config = notify_config.get(key, {})
            if isinstance(channel_config, dict):
                merged = _deep_merge(merged, channel_config)
        return merged
