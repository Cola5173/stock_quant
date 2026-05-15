"""股票列表服务"""
import os
from typing import List

import pandas as pd

from api.config import settings
from api.schemas.models import StockItem

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _resolve(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def list_stocks() -> List[StockItem]:
    """从 resource/stock_names.csv 读取股票列表"""
    csv_path = _resolve(settings.STOCK_NAMES_FILE)
    if not os.path.exists(csv_path):
        return []

    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8-sig")
    items: List[StockItem] = []
    for _, row in df.iterrows():
        code = str(row["symbol"]).strip()
        name = str(row.get("name", "")).strip()
        exchange = "SH" if code.startswith("6") else "SZ"
        label = f"{name} ({code}.{exchange})" if name else f"{code}.{exchange}"
        items.append(StockItem(code=code, name=name, label=label, exchange=exchange))
    return items
