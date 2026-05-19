"""选股结果 API 路由"""
import logging
import os
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from api.config import settings
from api.services.selected_service import (
    list_strategies,
    list_records,
    get_record_detail,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/selected", tags=["selected"])


@router.get("/strategies")
def get_strategies() -> List[Dict[str, str]]:
    return list_strategies()


@router.get("/{strategy}/records")
def get_records(strategy: str) -> List[Dict[str, Any]]:
    return list_records(strategy)


@router.get("/{strategy}/{date}")
def get_detail(strategy: str, date: str) -> Dict[str, Any]:
    result = get_record_detail(strategy, date)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该日期的选股记录")
    return result


@router.post("/{strategy}/run")
def run_scan(strategy: str, date: str = None) -> Dict[str, Any]:
    """对当前选中策略执行当天选股扫描"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    from api.scanner.scanner import Scanner

    # 加载股票池
    stock_list_file = settings.STOCK_LIST_CACHE
    if not os.path.exists(stock_list_file):
        stock_list_file = settings.STOCK_CODE_FILE
    if not os.path.exists(stock_list_file):
        raise HTTPException(500, "未找到股票列表文件")

    stock_codes = []
    with open(stock_list_file, "r", encoding="utf-8-sig") as f:
        for line in f:
            code = line.strip()
            if code:
                stock_codes.append(code)

    if not stock_codes:
        raise HTTPException(500, "股票列表为空")

    try:
        scanner = Scanner(strategy, stock_codes)
        candidates = scanner.scan(date)
        scanner.save_to_selected(candidates, date)
        return {
            "status": "ok",
            "date": date,
            "strategy": strategy,
            "candidates_count": len(candidates),
        }
    except Exception as e:
        logger.error(f"选股失败: {e}", exc_info=True)
        raise HTTPException(500, f"选股失败: {e}")
