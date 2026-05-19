"""首页统计概览：股票数 / 策略数 / 数据源数"""
import os

from api.config import settings
from api.schemas.models import HomeStats
from api.services.backtest_service import STRATEGY_REGISTRY

DATA_SOURCES = ["tushare", "akshare"]  # baostock 已弃用，不计入统计
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def get_home_stats() -> HomeStats:
    stock_code_path = settings.STOCK_CODE_FILE
    if not os.path.isabs(stock_code_path):
        stock_code_path = os.path.join(PROJECT_ROOT, stock_code_path)

    stock_count = 0
    if os.path.exists(stock_code_path):
        with open(stock_code_path, "r", encoding="utf-8-sig") as f:
            stock_count = sum(1 for line in f if line.strip())

    return HomeStats(
        stock_count=stock_count,
        strategy_count=len(STRATEGY_REGISTRY),
        data_source_count=len(DATA_SOURCES),
    )
