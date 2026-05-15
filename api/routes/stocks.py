"""股票相关路由"""
from typing import List
from fastapi import APIRouter, HTTPException, Query

from api.schemas.models import StockItem, KlineBar
from api.services.stock_service import list_stocks
from api.services.kline_service import load_kline

router = APIRouter(prefix="/api/stocks", tags=["stocks"])


@router.get("", response_model=List[StockItem])
def get_stocks():
    """全市场 A 股列表（来自 resource/stock_names.csv）"""
    items = list_stocks()
    if not items:
        raise HTTPException(status_code=404, detail="股票列表为空，请生成 resource/stock_names.csv")
    return items


@router.get("/{code}/kline", response_model=List[KlineBar])
def get_kline(
    code: str,
    start: str = Query(..., description="开始日期 YYYY-MM-DD"),
    end: str = Query(..., description="结束日期 YYYY-MM-DD"),
):
    """单股 K 线数据"""
    bars = load_kline(code, start, end)
    if not bars:
        raise HTTPException(status_code=404, detail=f"未找到 {code} 在 [{start}, {end}] 的数据")
    return bars
