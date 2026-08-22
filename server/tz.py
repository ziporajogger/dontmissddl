"""统一时区：全项目使用北京时间（UTC+8）。

LLM 输出的 deadline 是无时区字符串（如 "2026-09-15T23:59:00"），
语义上是北京时间。所有「解析无时区字符串」和「取当前时间」都
统一用 BEIJING_TZ，避免 8 小时偏差。
"""

from datetime import timedelta, timezone

BEIJING_TZ = timezone(timedelta(hours=8))
