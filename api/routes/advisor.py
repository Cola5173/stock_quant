"""实盘 advisor 接口"""
import json
import os
from datetime import datetime
from glob import glob

from fastapi import APIRouter, HTTPException

from api.config import settings
from api.advisor.decision_engine import run_decision
from api.utils.trade_calendar import get_target_trade_date
from api.services import trade_service

router = APIRouter(prefix="/api", tags=["advisor"])


@router.get("/advisor/latest")
def advisor_latest():
    """返回当前持仓 + 最新决策。
    持仓由 transactions 派生（trade_service），不再直接读 positions.json。"""
    state = trade_service.get_state()
    positions_payload = {
        "total_capital": state["total_capital"],
        "positions": state["positions"],
    }
    decision = _load_latest_decision()
    return {
        "positions": positions_payload,
        "decision": decision,
    }


@router.get("/advisor/transactions")
def list_transactions():
    """返回交易流水 + 派生持仓"""
    return trade_service.get_state()


@router.post("/advisor/transactions")
def create_transaction(tx: dict):
    """追加一笔交易（B 买入 / S 卖出）"""
    try:
        record = trade_service.add_transaction(tx)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"status": "ok", "transaction": record}


@router.delete("/advisor/transactions/{tx_id}")
def remove_transaction(tx_id: str):
    """删除指定交易（撤销误操作）"""
    try:
        return trade_service.delete_transaction(tx_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/advisor/total-capital")
def update_total_capital(data: dict):
    """更新总资金（仅此一项可手动改，持仓由交易流水派生）"""
    value = data.get("total_capital")
    if not isinstance(value, (int, float)):
        raise HTTPException(400, "total_capital 必须是数字")
    try:
        return trade_service.set_total_capital(float(value))
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/advisor/run-decision")
def trigger_decision(date: str = None, strategy: str = "b1_small"):
    """手动触发决策计算。
    未传 date 时，对齐到「最近已收盘交易日」——盘前/盘中/周末/节假日点击，
    会自动用上一个完整 K 线日作为决策日，避免出现「数据未更新，仅参考」。
    """
    if not date:
        date = get_target_trade_date().strftime("%Y-%m-%d")
    decision = run_decision(date, strategy_key=strategy)
    from api.advisor.decision_engine import _serialize_holding
    return {
        "date": decision.date,
        "strategy": decision.strategy,
        "next_trading_date": decision.next_trading_date,
        "market": decision.market,
        "cooldown": decision.cooldown,
        "holdings": [_serialize_holding(h) for h in decision.holdings],
        "actions": [vars(a) if hasattr(a, '__dict__') else a for a in decision.actions],
        "warnings": decision.warnings,
        "has_latest_data": decision.has_latest_data,
    }


def _load_latest_decision() -> dict | None:
    pattern = os.path.join(settings.DECISIONS_DIR, "decision_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)
