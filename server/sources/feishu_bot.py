"""Feishu Bot integration — message handling, webhook, and sending."""

import json
import os
import time
import requests


class FeishuBot:
    """Feishu (Lark) Bot client."""

    def __init__(self):
        self.app_id = os.environ["FEISHU_APP_ID"]
        self.app_secret = os.environ["FEISHU_APP_SECRET"]
        self._tenant_token: str | None = None
        self._token_expiry: float = 0

    # ── Auth ──────────────────────────────────────────

    def _get_tenant_token(self) -> str:
        """Get or refresh tenant access token."""
        if self._tenant_token and time.time() < self._token_expiry:
            return self._tenant_token

        resp = requests.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        self._tenant_token = data["tenant_access_token"]
        self._token_expiry = time.time() + data.get("expire", 7200) - 300
        return self._tenant_token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_tenant_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # ── Message reading ───────────────────────────────

    def get_message_content(self, message_id: str) -> dict | None:
        """Fetch full message content by message_id."""
        try:
            resp = requests.get(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            item = data.get("data", {}).get("items", [{}])[0]
            body = item.get("body", {}).get("content", "{}")
            return json.loads(body)
        except Exception:
            return None

    def list_messages(self, chat_id: str, page_size: int = 50,
                      start_time: str | None = None) -> list[dict]:
        """List messages in a chat (for batch processing)."""
        params = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": min(page_size, 50),
            "sort_type": "ByCreateTimeDesc",
        }
        if start_time:
            params["start_time"] = start_time

        try:
            resp = requests.get(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                headers=self._headers(),
                params=params,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("data", {}).get("items", [])
        except Exception:
            return []

    # ── Message sending ────────────────────────────────

    def send_text(self, chat_id: str, text: str) -> bool:
        """Send a text message to a chat."""
        content = json.dumps({"text": text})
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": content,
        }
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def send_dm(self, open_id: str, text: str) -> bool:
        """Send a direct (private) message to a user by open_id."""
        content = json.dumps({"text": text})
        body = {
            "receive_id": open_id,
            "msg_type": "text",
            "content": content,
        }
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def lookup_open_id(self, email: str = "", mobile: str = "") -> str | None:
        """Look up a user's open_id by email or mobile.
        Requires contact:user.id:readonly permission on the Feishu app."""
        try:
            payload = {}
            if mobile:
                payload["mobiles"] = [mobile]
            elif email:
                payload["emails"] = [email]
            else:
                return None

            resp = requests.post(
                "https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id"
                "?user_id_type=open_id",
                headers=self._headers(),
                json=payload,
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"  API error code={data.get('code')}, msg={data.get('msg')}")
                return None
            user_list = data.get("data", {}).get("user_list", [])
            if user_list:
                u = user_list[0]
                uid = u.get("user_id") or u.get("open_id") or u.get("union_id")
                return uid
            else:
                print("  No matching user found in this tenant")
        except Exception as e:
            print(f"[Feishu] lookup_open_id failed: {e}")
        return None

    def send_card(self, chat_id: str, title: str, items: list[dict]) -> bool:
        """Send a rich card message (for DDL reminders)."""
        elements = []
        for item in items[:5]:  # max 5 per card
            days_left = item.get("days_left", "")
            elements.append({
                "tag": "div",
                "fields": [
                    {"is_short": False, "text": {"tag": "lark_md",
                         "content": f"**{item['title']}**"}},
                    {"is_short": True, "text": {"tag": "lark_md",
                         "content": f"⏰ {item['deadline']}"}},
                ]
            })
            if days_left:
                elements.append({
                    "tag": "markdown",
                    "content": f"⏳ 还有 **{days_left}** 天"
                })
            elements.append({"tag": "hr"})

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "red",
            },
            "elements": elements,
        }

        body = {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    def reply_text(self, message_id: str, text: str) -> bool:
        """Reply to a specific message in thread."""
        content = json.dumps({"text": text})
        body = {
            "content": content,
            "msg_type": "text",
        }
        try:
            resp = requests.post(
                f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
                headers=self._headers(),
                json=body,
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False
