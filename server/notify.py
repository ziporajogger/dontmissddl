"""通知后端抽象层（可插拔，可选）。

只做单向推送（把消息送到手机 / 桌面）。「点按钮改状态」的交互仍由
飞书多维表格工作流负责（零服务器收不到回调）。

每个通知器实现 send(text) -> bool。按环境变量决定启用哪些（可同时多个）。
"""

from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText

import requests


class Notifier:
    name = "notifier"

    def send(self, text: str) -> bool:
        raise NotImplementedError


class FeishuNotifier(Notifier):
    """代码发飞书消息（复用 FeishuBot，走群 chat_id）。"""

    name = "feishu"

    def __init__(self, chat_id: str):
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        from server.sources.feishu_bot import FeishuBot
        return FeishuBot().send_text(self.chat_id, text)


class TelegramNotifier(Notifier):
    """Telegram Bot（HTTP 直连，无需服务器）。"""

    name = "telegram"

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False


class NtfyNotifier(Notifier):
    """ntfy.sh —— 免费 push 到手机（手机装 ntfy App 订阅同名 topic）。"""

    name = "ntfy"

    def __init__(self, topic: str):
        self.topic = topic

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                f"https://ntfy.sh/{self.topic}",
                data=text.encode("utf-8"),
                headers={"Title": "dontmissddl 提醒"},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False


class WebhookNotifier(Notifier):
    """钉钉 / 企业微信群机器人 webhook，均接受 text 类型 payload。"""

    def __init__(self, name: str, webhook: str):
        self.name = name
        self.webhook = webhook

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                self.webhook,
                json={"msgtype": "text", "text": {"content": text}},
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False


class EmailNotifier(Notifier):
    """SMTP 发邮件提醒（区别于信息源里的 IMAP 收邮件）。"""

    name = "email"

    def __init__(self, host: str, port: str, user: str, password: str, to: str):
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.to = to

    def send(self, text: str) -> bool:
        try:
            msg = MIMEText(text, "plain", "utf-8")
            msg["Subject"] = "dontmissddl 提醒"
            msg["From"] = self.user
            msg["To"] = self.to
            with smtplib.SMTP_SSL(self.host, self.port, timeout=15) as s:
                s.login(self.user, self.password)
                s.sendmail(self.user, [self.to], msg.as_string())
            return True
        except Exception:
            return False


def get_notifiers() -> list[Notifier]:
    """按环境变量返回启用的通知器（可多个）。"""
    notifiers: list[Notifier] = []

    feishu_chat = os.environ.get("NOTIFY_FEISHU_CHAT_ID", "")
    if feishu_chat:
        notifiers.append(FeishuNotifier(feishu_chat))

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    if tg_token and tg_chat:
        notifiers.append(TelegramNotifier(tg_token, tg_chat))

    ntfy_topic = os.environ.get("NTFY_TOPIC", "")
    if ntfy_topic:
        notifiers.append(NtfyNotifier(ntfy_topic))

    dingtalk = os.environ.get("DINGTALK_WEBHOOK", "")
    if dingtalk:
        notifiers.append(WebhookNotifier("dingtalk", dingtalk))

    wecom = os.environ.get("WECOM_WEBHOOK", "")
    if wecom:
        notifiers.append(WebhookNotifier("wecom", wecom))

    email_host = os.environ.get("NOTIFY_EMAIL_HOST", "")
    email_user = os.environ.get("NOTIFY_EMAIL_USER", "")
    if email_host and email_user:
        notifiers.append(EmailNotifier(
            email_host,
            os.environ.get("NOTIFY_EMAIL_PORT", "465"),
            email_user,
            os.environ.get("NOTIFY_EMAIL_PASSWORD", ""),
            os.environ.get("NOTIFY_EMAIL_TO", email_user),
        ))

    return notifiers
