"""
A 股交易日历工具

提供两个核心能力：
1. is_trading_day(date) — 是否交易日（chinese_calendar，未安装则退化为非周末）
2. get_target_trade_date(now) — "本次拉取应当对齐到的最近交易日"
   规则：
     - 当前时间 ≥ DATA_AVAILABLE_HOUR 且今天是交易日 → 今天
     - 否则（盘前 / 盘中 / 周末 / 节假日） → 往前找最近的交易日
   这样可以避免盘中点"拉取最新数据"时拿到不完整 K 线。
"""
from datetime import date, datetime, timedelta
from typing import Union

# AkShare/东财日 K 线一般在 15:30 之后才稳定有当日完整数据；保守取 15:00
DATA_AVAILABLE_HOUR = 15


def is_trading_day(d: Union[date, datetime, str]) -> bool:
    """是否交易日。chinese_calendar 不可用时退化为「非周末」"""
    if isinstance(d, str):
        d = datetime.strptime(d, "%Y-%m-%d").date()
    elif isinstance(d, datetime):
        d = d.date()

    try:
        import chinese_calendar as calendar
        return calendar.is_workday(d) and d.weekday() < 5
    except Exception:
        return d.weekday() < 5


def get_target_trade_date(now: datetime = None) -> date:
    """
    返回本次"拉取最新数据"应当对齐到的目标交易日。

    场景示例：
      - 周一 14:00（盘中）→ 上周五（今天数据未就绪）
      - 周一 15:30（盘后）→ 周一
      - 周六任意时间      → 周五
      - 国庆假期          → 节前最后一个交易日
    """
    now = now or datetime.now()
    today = now.date()

    if is_trading_day(today) and now.hour >= DATA_AVAILABLE_HOUR:
        return today

    probe = today - timedelta(days=1)
    for _ in range(15):  # 最长跨春节 7 天 + 缓冲
        if is_trading_day(probe):
            return probe
        probe -= timedelta(days=1)

    return today  # 兜底：极端情况下返回今天，调用方自行处理
