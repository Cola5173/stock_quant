"""策略 + 回测路由"""
from typing import List
from fastapi import APIRouter, HTTPException

from api.schemas.models import StrategyItem, BacktestRequest, BacktestResponse
from api.services.backtest_service import list_strategies, run_backtest

router = APIRouter(prefix="/api", tags=["backtest"])


@router.get("/strategies", response_model=List[StrategyItem])
def get_strategies():
    """可用策略列表"""
    return list_strategies()


@router.post("/backtest", response_model=BacktestResponse)
def post_backtest(req: BacktestRequest):
    """触发单股回测，同步返回结果"""
    try:
        return run_backtest(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"回测失败: {e}")
