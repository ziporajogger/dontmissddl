"""Feishu Bitable (多维表格) integration — write DDL records, list for dedup."""

import json
import os
import time
from datetime import datetime, timezone

import requests


class FeishuBitable:
    """Client for Feishu Bitable API."""

    def __init__(self):
        self.app_id = os.environ["FEISHU_APP_ID"]
        self.app_secret = os.environ["FEISHU_APP_SECRET"]
        self._tenant_token: str | None = None
        self._token_expiry: float = 0

    def _get_tenant_token(self) -> str:
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

    # ── Wiki → Bitable token ──────────────────────────

    def resolve_bitable_token(self, wiki_token: str) -> str | None:
        """Resolve a wiki node token to its Bitable app_token."""
        try:
            resp = requests.get(
                f"https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node",
                headers=self._headers(),
                params={"token": wiki_token},
                timeout=10,
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"[Bitable] get_node error: code={data.get('code')}, msg={data.get('msg')}")
                return None
            node = data.get("data", {}).get("node", {})
            obj_type = node.get("obj_type", "")
            obj_token = node.get("obj_token", "")
            if obj_type != "bitable":
                print(f"[Bitable] Not a Bitable node: obj_type={obj_type}")
                return None
            print(f"[Bitable] Resolved app_token: {obj_token}")
            return obj_token
        except Exception as e:
            print(f"[Bitable] resolve error: {e}")
            return None

    # ── Records ───────────────────────────────────────

    def list_records(self, app_token: str, table_id: str,
                     page_size: int = 100) -> list[dict]:
        """Fetch existing records from a Bitable table (for dedup)."""
        records: list[dict] = []
        page_token: str | None = None
        while True:
            params = {"page_size": min(page_size, 100)}
            if page_token:
                params["page_token"] = page_token
            try:
                resp = requests.get(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
                    f"/tables/{table_id}/records",
                    headers=self._headers(),
                    params=params,
                    timeout=15,
                )
                data = resp.json()
                if data.get("code") != 0:
                    print(f"[Bitable] list error: {data.get('msg')}")
                    break
                items = data.get("data", {}).get("items", [])
                records.extend(items)
                if not data.get("data", {}).get("has_more"):
                    break
                page_token = data.get("data", {}).get("page_token", "")
            except Exception as e:
                print(f"[Bitable] list request error: {e}")
                break
        return records

    def add_records(self, app_token: str, table_id: str,
                    fields_list: list[dict]) -> int:
        """Batch-add records to a Bitable table. Returns number added."""
        if not fields_list:
            return 0

        added = 0
        # Bitable API allows up to 500 records per batch
        BATCH_SIZE = 100
        for i in range(0, len(fields_list), BATCH_SIZE):
            batch = fields_list[i : i + BATCH_SIZE]
            body = {"records": [{"fields": f} for f in batch]}
            try:
                resp = requests.post(
                    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
                    f"/tables/{table_id}/records/batch_create",
                    headers=self._headers(),
                    json=body,
                    timeout=30,
                )
                data = resp.json()
                if data.get("code") != 0:
                    print(f"[Bitable] batch_create error: code={data.get('code')}, msg={data.get('msg')}")
                    continue
                records = data.get("data", {}).get("records", [])
                added += len(records)
            except Exception as e:
                print(f"[Bitable] batch_create request error: {e}")
                continue
        return added

    def update_record(self, app_token: str, table_id: str,
                      record_id: str, fields: dict) -> bool:
        """Update a single record."""
        try:
            resp = requests.put(
                f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}"
                f"/tables/{table_id}/records/{record_id}",
                headers=self._headers(),
                json={"fields": fields},
                timeout=10,
            )
            return resp.json().get("code") == 0
        except Exception:
            return False


def _format_source(source: str, source_group: str) -> str:
    """Human-readable source label."""
    labels = {
        "email": "📧 邮件",
        "feishu": "💬 飞书群聊",
        "wechat_rss": "📰 公众号RSS",
        "sogou_wechat": "📰 公众号",
        "manual": "✍️ 手动添加",
    }
    label = labels.get(source, source)
    if source_group:
        # Trim quotes and angle brackets for email senders
        import re
        clean_group = re.sub(r'^["\'<]|["\'>]$', '', source_group.strip())
        # For email, just use sender name (part before <email>)
        if "<" in clean_group:
            clean_group = clean_group.split("<")[0].strip().strip('"')
        return f"{label}: {clean_group}"
    return label


def build_ddl_fields(ddl: dict) -> dict | None:
    """Convert an internal DDL dict to Bitable field values.

    Returns None for past deadlines (skip these).
    """
    deadline_str = ddl.get("deadline", "")
    deadline_ts = None
    if deadline_str:
        try:
            dt = datetime.fromisoformat(deadline_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            # Skip past deadlines
            if dt < datetime.now(timezone.utc):
                return None
            deadline_ts = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            pass

    # Use DDL's own created_at if available, otherwise today
    created_str = ddl.get("created_at", "")
    add_date_ts = None
    if created_str:
        try:
            add_dt = datetime.fromisoformat(created_str)
            if add_dt.tzinfo is None:
                add_dt = add_dt.replace(tzinfo=timezone.utc)
            add_date_ts = int(datetime(add_dt.year, add_dt.month, add_dt.day, tzinfo=timezone.utc).timestamp() * 1000)
        except (ValueError, TypeError):
            pass
    if add_date_ts is None:
        now = datetime.now(timezone.utc)
        add_date_ts = int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp() * 1000)

    return {
        "标题": ddl.get("title", ""),
        "状态": "待办",
        "截止日期": deadline_ts,
        "描述": ddl.get("description", ""),
        "来源": _format_source(ddl.get("source", "unknown"), ddl.get("source_group", "")),
        "原始文本": ddl.get("raw_text", "")[:5000],
        "提醒状态": "",
        "添加日期": now_ts,
    }
