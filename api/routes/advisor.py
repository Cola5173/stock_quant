"""实盘 advisor 接口"""
import json
import os
import tempfile
from datetime import datetime
from glob import glob

from fastapi import APIRouter, HTTPException

from api.config import settings
from api.advisor.decision_engine import run_decision

router = APIRouter(prefix="/api", tags=["advisor"])


@router.get("/advisor/latest")
def advisor_latest():
    """返回当前持仓 + 最新决策"""
    positions = _load_positions()
    decision = _load_latest_decision()
    return {
        "positions": positions,
        "decision": decision,
    }


@router.put("/advisor/positions")
def update_positions(data: dict):
    """更新 positions.json"""
    _validate_positions(data)
    _save_positions(data)
    return {"status": "ok"}


@router.post("/advisor/run-decision")
def trigger_decision(date: str = None):
    """手动触发决策计算"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    decision = run_decision(date)
    from api.advisor.decision_engine import _serialize_holding
    return {
        "date": decision.date,
        "next_trading_date": decision.next_trading_date,
        "market": decision.market,
        "cooldown": decision.cooldown,
        "holdings": [_serialize_holding(h) for h in decision.holdings],
        "actions": [vars(a) if hasattr(a, '__dict__') else a for a in decision.actions],
        "warnings": decision.warnings,
        "has_latest_data": decision.has_latest_data,
    }


def _load_positions() -> dict:
    path = settings.POSITIONS_FILE
    if not os.path.exists(path):
        return {"total_capital": 0, "positions": [], "cash": 0}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_latest_decision() -> dict | None:
    pattern = os.path.join(settings.DECISIONS_DIR, "decision_*.json")
    files = sorted(glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0], "r", encoding="utf-8") as f:
        return json.load(f)


def _validate_positions(data: dict):
    """校验 positions.json 格式"""
    if "total_capital" not in data or not isinstance(data["total_capital"], (int, float)):
        raise HTTPException(400, "total_capital 必须是数字")
    if data["total_capital"] <= 0:
        raise HTTPException(400, "total_capital 必须 > 0")

    positions = data.get("positions", [])
    if not isinstance(positions, list):
        raise HTTPException(400, "positions 必须是数组")

    for i, p in enumerate(positions):
        if not isinstance(p, dict):
            raise HTTPException(400, f"positions[{i}] 必须是对象")

        symbol = p.get("symbol", "")
        if not (isinstance(symbol, str) and symbol.isdigit() and len(symbol) == 6):
            raise HTTPException(400, f"positions[{i}].symbol 必须是 6 位数字")

        shares = p.get("shares")
        if not isinstance(shares, int) or shares <= 0:
            raise HTTPException(400, f"positions[{i}].shares 必须是正整数")

        cost_price = p.get("cost_price")
        if not isinstance(cost_price, (int, float)) or cost_price <= 0:
            raise HTTPException(400, f"positions[{i}].cost_price 必须是正数")

        buy_date = p.get("buy_date", "")
        if not isinstance(buy_date, str) or not buy_date:
            raise HTTPException(400, f"positions[{i}].buy_date 必须是字符串")
        # 简单日期格式校验
        try:
            datetime.strptime(buy_date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(400, f"positions[{i}].buy_date 格式错误，应为 YYYY-MM-DD")


def _save_positions(data: dict):
    """原子写 positions.json"""
    os.makedirs(os.path.dirname(settings.POSITIONS_FILE), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(settings.POSITIONS_FILE), suffix=".tmp"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, settings.POSITIONS_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
