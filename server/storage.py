"""存储后端抽象层。

目前有两个后端，通过环境变量二选一：
  - 飞书多维表格（Feishu Bitable）—— 默认
  - Google Calendar —— 可选，DDL 写成带提醒的日历事件

以后要支持其它存储，新增一个类实现同样的接口，再在 get_storage() 里按
配置返回即可，调用方（server/main.py）不用改。

接口约定：
  list_existing() -> set[tuple[str, str]]   返回已存在的 (标题, 截止日期)
  list_ddls() -> list[dict]                 返回所有记录（含状态），供提醒扫描
  add(ddls: list[dict]) -> int              批量写入内部 DDL 字典，返回成功条数
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from server.tz import BEIJING_TZ
from server.sources.feishu_bitable import FeishuBitable, build_ddl_fields


class Storage:
    def list_existing(self) -> set[tuple[str, str]]:
        raise NotImplementedError

    def list_ddls(self) -> list[dict]:
        """返回所有 DDL 记录：[{'title', 'deadline', 'status'}]，供提醒扫描。

        默认从 list_existing() 派生，status 置空（视为「待办」）。
        需要感知状态的存储（如飞书多维表格）可覆盖此方法。
        """
        return [{"title": t, "deadline": d, "status": ""} for t, d in self.list_existing()]

    def add(self, ddls: list[dict]) -> int:
        raise NotImplementedError


class FeishuBitableStorage(Storage):
    """飞书多维表格存储。"""

    def __init__(self, app_token: str, table_id: str):
        self.bt = FeishuBitable()
        self.app_token = app_token
        self.table_id = table_id

    @staticmethod
    def _deadline_iso(ts) -> str:
        if not ts:
            return ""
        try:
            return datetime.fromtimestamp(ts / 1000, tz=BEIJING_TZ).replace(tzinfo=None).isoformat()
        except Exception:
            return ""

    def list_ddls(self) -> list[dict]:
        out = []
        for rec in self.bt.list_records(self.app_token, self.table_id):
            f = rec.get("fields", {})
            out.append({
                "title": f.get("标题", ""),
                "deadline": self._deadline_iso(f.get("截止日期")),
                "status": f.get("状态", "") or "待办",
            })
        return out

    def list_existing(self) -> set[tuple[str, str]]:
        return {(d["title"], d["deadline"]) for d in self.list_ddls()}

    def add(self, ddls: list[dict]) -> int:
        fields_list = []
        for ddl in ddls:
            fields = build_ddl_fields(ddl)
            if fields is not None:  # None = 已过期，跳过
                fields_list.append(fields)
        if not fields_list:
            return 0
        return self.bt.add_records(self.app_token, self.table_id, fields_list)


class GoogleCalendarStorage(Storage):
    """Google Calendar 存储：DDL 写成带提醒的日历事件，由 Google 推送提醒。

    用服务账号（零服务器）：把日历 ID 分享给服务账号邮箱即可读写。
    """

    def __init__(self, service_account_json: str, calendar_id: str):
        import json
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        info = json.loads(service_account_json)
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/calendar"]
        )
        self.service = build("calendar", "v3", credentials=creds)
        self.calendar_id = calendar_id

    def list_ddls(self) -> list[dict]:
        out = []
        page_token = None
        while True:
            try:
                events = self.service.events().list(
                    calendarId=self.calendar_id,
                    singleEvents=True,
                    pageToken=page_token,
                ).execute()
            except Exception as e:
                print(f"[GCal] list error: {e}")
                break
            for e in events.get("items", []):
                start = e.get("start", {})
                out.append({
                    "title": e.get("summary", ""),
                    "deadline": start.get("dateTime") or start.get("date") or "",
                    "status": "",
                })
            page_token = events.get("nextPageToken")
            if not page_token:
                break
        return out

    def list_existing(self) -> set[tuple[str, str]]:
        return {(d["title"], d["deadline"]) for d in self.list_ddls()}

    def add(self, ddls: list[dict]) -> int:
        added = 0
        now = datetime.now(BEIJING_TZ)
        for ddl in ddls:
            deadline_str = ddl.get("deadline", "")
            try:
                dt = datetime.fromisoformat(deadline_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=BEIJING_TZ)
                if dt < now:
                    continue
            except (ValueError, TypeError):
                continue

            body = {
                "summary": ddl.get("title", ""),
                "description": ddl.get("description", ""),
                "start": {"dateTime": dt.isoformat(), "timeZone": "Asia/Shanghai"},
                "end": {"dateTime": (dt + timedelta(minutes=30)).isoformat(),
                        "timeZone": "Asia/Shanghai"},
                "reminders": {
                    "useDefault": False,
                    "overrides": [
                        {"method": "popup", "minutes": 3 * 24 * 60},
                        {"method": "popup", "minutes": 24 * 60},
                    ],
                },
            }
            try:
                self.service.events().insert(calendarId=self.calendar_id, body=body).execute()
                added += 1
            except Exception as e:
                print(f"[GCal] insert error: {e}")
        return added


def get_storage() -> Storage | None:
    """按环境变量返回存储后端；没配置返回 None。

    二选一：配了 Google Calendar（GOOGLE_CALENDAR_ID + GOOGLE_SERVICE_ACCOUNT）
    就用它，否则用飞书多维表格。
    """
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "")
    service_account = os.environ.get("GOOGLE_SERVICE_ACCOUNT", "")
    if calendar_id and service_account:
        return GoogleCalendarStorage(service_account, calendar_id)

    app_token = os.environ.get("FEISHU_APP_TOKEN", "")
    table_id = os.environ.get("FEISHU_TABLE_ID", "")
    if app_token and table_id:
        return FeishuBitableStorage(app_token, table_id)
    return None
