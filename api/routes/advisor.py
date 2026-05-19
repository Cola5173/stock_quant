"""实盘 advisor 接口"""
import json
import os
from glob import glob

from fastapi import APIRouter

from api.config import settings

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
