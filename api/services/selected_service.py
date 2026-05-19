"""选股结果服务：读取 selected/ 目录下的历史选股记录"""
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional

from api.config import settings

logger = logging.getLogger(__name__)

SELECTED_DIR = os.path.join(settings.PROJECT_ROOT, "selected")


def list_strategies() -> List[Dict[str, str]]:
    from api.services.backtest_service import STRATEGY_REGISTRY
    return [
        {"key": k, "name": name}
        for k, (name, _, _) in STRATEGY_REGISTRY.items()
    ]


def list_records(strategy: str) -> List[Dict[str, Any]]:
    """扫描 selected/{yyyy-mm-dd}/{strategy}.json，返回指定策略的所有日期记录"""
    if not os.path.isdir(SELECTED_DIR):
        return []

    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    records = []

    for name in os.listdir(SELECTED_DIR):
        if not date_pattern.match(name):
            continue
        result_path = os.path.join(SELECTED_DIR, name, f"{strategy}.json")
        if not os.path.isfile(result_path):
            continue
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = data.get("candidates_count", 0)
        except Exception:
            count = 0
        records.append({"date": name, "count": count})

    records.sort(key=lambda r: r["date"], reverse=True)
    return records


def get_record_detail(strategy: str, date: str) -> Optional[Dict[str, Any]]:
    """读取指定策略+日期的选股结果"""
    result_path = os.path.join(SELECTED_DIR, date, f"{strategy}.json")
    if not os.path.isfile(result_path):
        return None
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取选股结果失败 {result_path}: {e}")
        return None
