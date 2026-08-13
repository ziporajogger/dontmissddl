"""存储后端抽象层。

目前只有一个后端：飞书多维表格（Feishu Bitable）。
以后要支持其它存储（Google Sheets、JSON、SQLite……），新增一个类实现同样的
接口，再在 get_storage() 里按配置返回即可，调用方（server/main.py）不用改。

接口约定：
  list_existing() -> set[tuple[str, str]]   返回已存在的 (标题, 截止日期)
  add(ddls: list[dict]) -> int              批量写入内部 DDL 字典，返回成功条数
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from server.sources.feishu_bitable import FeishuBitable, build_ddl_fields


class Storage:
    def list_existing(self) -> set[tuple[str, str]]:
        raise NotImplementedError

    def add(self, ddls: list[dict]) -> int:
        raise NotImplementedError


class FeishuBitableStorage(Storage):
    """飞书多维表格存储。"""

    def __init__(self, app_token: str, table_id: str):
        self.bt = FeishuBitable()
        self.app_token = app_token
        self.table_id = table_id

    def list_existing(self) -> set[tuple[str, str]]:
        seen: set[tuple[str, str]] = set()
        for rec in self.bt.list_records(self.app_token, self.table_id):
            f = rec.get("fields", {})
            title = f.get("标题", "")
            deadline = ""
            dl_ts = f.get("截止日期")
            if dl_ts:
                try:
                    deadline = datetime.fromtimestamp(dl_ts / 1000, tz=timezone.utc).isoformat()
                except Exception:
                    pass
            seen.add((title, deadline))
        return seen

    def add(self, ddls: list[dict]) -> int:
        fields_list = []
        for ddl in ddls:
            fields = build_ddl_fields(ddl)
            if fields is not None:  # None = 已过期，跳过
                fields_list.append(fields)
        if not fields_list:
            return 0
        return self.bt.add_records(self.app_token, self.table_id, fields_list)


def get_storage() -> Storage | None:
    """按环境变量返回存储后端；没配置返回 None。"""
    app_token = os.environ.get("FEISHU_APP_TOKEN", "")
    table_id = os.environ.get("FEISHU_TABLE_ID", "")
    if app_token and table_id:
        return FeishuBitableStorage(app_token, table_id)
    return None
