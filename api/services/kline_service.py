"""K 线数据服务"""
import os
from typing import List

import pandas as pd

from api.config import settings
from api.schemas.models import KlineBar

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_kline(stock_code: str, start: str, end: str) -> List[KlineBar]:
    """加载单股 K 线数据。start/end 为 YYYY-MM-DD"""
    data_dir = settings.DATA_DIR
    if not os.path.isabs(data_dir):
        data_dir = os.path.join(PROJECT_ROOT, data_dir)
    csv_path = os.path.join(data_dir, f"{stock_code}.csv")
    if not os.path.exists(csv_path):
        return []

    df = pd.read_csv(csv_path, parse_dates=["date"])
    df = df[(df["date"] >= start) & (df["date"] <= end)]
    df = df.sort_values("date").reset_index(drop=True)

    bars: List[KlineBar] = []
    for _, row in df.iterrows():
        bars.append(KlineBar(
            date=row["date"].strftime("%Y-%m-%d"),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row.get("volume", 0)),
        ))
    return bars
