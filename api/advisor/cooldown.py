"""连续亏损冷却判定"""
import json
import logging
import os

from api.config import settings

logger = logging.getLogger(__name__)


def load_closed_trades() -> list:
    path = settings.CLOSED_TRADES_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("trades", [])


def compute_cooldown_state(trades: list, today_idx: int) -> dict:
    """判定冷却状态。
    trades: closed_trades.json 中的 trades 列表（按时间正序）
    today_idx: 今日在交易日序列中的索引
    返回 {"active": bool, "remaining_days": int, "cooldown_until": int}
    """
    cfg = settings.ADVISOR_CONFIG
    streak = 0
    cooldown_until = -1

    full_clears = [t for t in trades if t.get("ratio", 0) >= 1.0]
    for t in full_clears:
        if t.get("pnl_pct", 0) < 0:
            streak += 1
            if streak >= cfg["cooldown_loss_streak"]:
                cooldown_until = today_idx + cfg["cooldown_offset"]
                streak = 0
        else:
            streak = 0

    active = today_idx < cooldown_until
    remaining = max(0, cooldown_until - today_idx) if active else 0
    return {"active": active, "remaining_days": remaining, "cooldown_until": cooldown_until}
