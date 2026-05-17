"""选股结果服务：读取 output/selected/ 目录下的历史选股记录"""
import json
import logging
import os
import re
from typing import List, Dict, Any, Optional

from api.config import settings

logger = logging.getLogger(__name__)

SELECTED_DIR = os.path.join(settings.PROJECT_ROOT, "selected")

STRATEGY_META = [
    {"key": "b1", "name": "趋势回调-b1"},
    {"key": "b2", "name": "趋势回调确认-b2"},
    {"key": "zxt", "name": "转形图"},
    {"key": "dz", "name": "单针"},
]


def list_strategies() -> List[Dict[str, str]]:
    return STRATEGY_META


def list_records(strategy: str) -> List[Dict[str, Any]]:
    """扫描 selected 目录，返回指定策略的所有日期记录"""
    if not os.path.isdir(SELECTED_DIR):
        return []

    pattern = re.compile(rf"^(\d{{4}}_\d{{2}}_\d{{2}})_{re.escape(strategy)}$")
    records = []

    for name in os.listdir(SELECTED_DIR):
        m = pattern.match(name)
        if not m:
            continue
        date_part = m.group(1).replace("_", "-")
        result_path = os.path.join(SELECTED_DIR, name, "result.json")
        if not os.path.isfile(result_path):
            continue
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            count = data.get("candidates_count", 0)
        except Exception:
            count = 0
        records.append({"date": date_part, "count": count})

    records.sort(key=lambda r: r["date"], reverse=True)
    return records


def get_record_detail(strategy: str, date: str) -> Optional[Dict[str, Any]]:
    """读取指定策略+日期的选股结果"""
    folder_name = f"{date.replace('-', '_')}_{strategy}"
    result_path = os.path.join(SELECTED_DIR, folder_name, "result.json")
    if not os.path.isfile(result_path):
        return None
    try:
        with open(result_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取选股结果失败 {result_path}: {e}")
        return None
