"""选股结果 API 路由"""
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from api.services.selected_service import (
    list_strategies,
    list_records,
    get_record_detail,
)

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
