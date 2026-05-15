"""股票列表服务"""
import os
from typing import List

import pandas as pd

from api.config import settings
from api.schemas.models import StockItem

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

INDICES = [
    {"code": "idx_000001_SH", "name": "上证指数", "exchange": "SH"},
    {"code": "idx_399001_SZ", "name": "深证成指", "exchange": "SZ"},
    {"code": "idx_399006_SZ", "name": "创业板指", "exchange": "SZ"},
    {"code": "idx_000300_SH", "name": "沪深300", "exchange": "SH"},
    {"code": "idx_000016_SH", "name": "上证50", "exchange": "SH"},
    {"code": "idx_000905_SH", "name": "中证500", "exchange": "SH"},
    {"code": "idx_883957_TI", "name": "同花顺全A指数", "exchange": "SH"},
]


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def list_stocks() -> List[StockItem]:
    """从 resource/stock_names.csv 读取股票列表，并包含常用指数"""
    items: List[StockItem] = []

    for idx in INDICES:
        label = f"{idx['name']} ({idx['code']})"
        items.append(StockItem(code=idx["code"], name=idx["name"], label=label, exchange=idx["exchange"]))

    csv_path = _resolve(settings.STOCK_NAMES_FILE)
    if not os.path.exists(csv_path):
        return items

    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    for _, row in df.iterrows():
        code = str(row["symbol"]).strip()
        name = str(row.get("name", "")).strip()
        exchange = "SH" if code.startswith("6") else "SZ"
        label = f"{name} ({code}.{exchange})" if name else f"{code}.{exchange}"
        items.append(StockItem(code=code, name=name, label=label, exchange=exchange))
    return items
