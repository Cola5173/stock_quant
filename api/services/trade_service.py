"""模拟盘交易记录服务

transactions.json 是唯一真相，positions.json 由交易流水派生。

数据模型：
- transactions.json: { total_capital, transactions: [...] }
- transaction: { id, type: "B"|"S", symbol, name, shares, price, trade_date, created_at }
  - price: 成本价（不含税费）
  - 买入时：cost_price = price；卖出时：price 是卖出价

派生持仓（按 symbol 加权平均）：
- 买入 B: shares += b.shares, cost_total += b.price * b.shares, buy_date = 首次未清仓的买入日
- 卖出 S: cost_total 按比例扣减；shares -= s.shares
- shares == 0 → 该 symbol 从持仓清出（包括 buy_date 重置）
"""
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from api.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TOTAL_CAPITAL = 200000

_lock = threading.Lock()
_name_map: Optional[Dict[str, str]] = None


def _get_name_map() -> Dict[str, str]:
    """加载 stock_names.csv → {symbol: name} 映射（懒加载 + 缓存）"""
    global _name_map
    if _name_map is not None:
        return _name_map
    csv_path = os.path.join(settings.PROJECT_ROOT, "api", "resource", "stock_names.csv")
    if not os.path.exists(csv_path):
        _name_map = {}
        return _name_map
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, dtype={"symbol": str})
        _name_map = dict(zip(df["symbol"].astype(str).str.strip(),
                             df["name"].astype(str).str.strip()))
    except Exception:
        _name_map = {}
    return _name_map


def _empty_state() -> dict:
    return {"total_capital": DEFAULT_TOTAL_CAPITAL, "transactions": []}


def _read_transactions() -> dict:
    path = settings.TRANSACTIONS_FILE
    if not os.path.exists(path):
        # 首次启动：从已有 positions.json 读出 total_capital，避免覆盖用户旧设置
        legacy_capital = _try_load_legacy_capital()
        state = _empty_state()
        if legacy_capital is not None:
            state["total_capital"] = legacy_capital
        return state
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _try_load_legacy_capital() -> Optional[float]:
    legacy_path = settings.POSITIONS_FILE
    if not os.path.exists(legacy_path):
        return None
    try:
        with open(legacy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        v = data.get("total_capital")
        return float(v) if v is not None else None
    except Exception:
        return None


def _atomic_write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def derive_positions(transactions: List[dict]) -> List[dict]:
    """根据交易流水按 symbol 加权平均派生当前持仓。
    返回结构与旧 positions[] 兼容：[{symbol, name, shares, cost_price, buy_date}]
    """
    sorted_txs = sorted(
        transactions,
        key=lambda t: (t.get("trade_date", ""), t.get("created_at", "")),
    )

    state: Dict[str, Dict] = {}
    for tx in sorted_txs:
        sym = tx.get("symbol", "")
        if not sym:
            continue
        kind = tx.get("type", "B").upper()
        shares = int(tx.get("shares") or 0)
        price = float(tx.get("price") or 0.0)
        if shares <= 0 or price <= 0:
            continue

        s = state.setdefault(sym, {
            "symbol": sym,
            "name": tx.get("name", sym),
            "shares": 0,
            "cost_total": 0.0,
            "buy_date": "",
        })
        # name 用最新一次出现的（用户可能改了名称映射）
        if tx.get("name"):
            s["name"] = tx["name"]

        if kind == "B":
            if s["shares"] == 0:
                # 重新建仓：buy_date 取这笔
                s["buy_date"] = tx.get("trade_date", "")
            s["shares"] += shares
            s["cost_total"] += price * shares
        elif kind == "S":
            if s["shares"] <= 0:
                logger.warning(f"卖出 {sym} 但当前无持仓，忽略")
                continue
            sell_shares = min(shares, s["shares"])
            # 加权平均：按比例扣 cost_total
            avg = s["cost_total"] / s["shares"] if s["shares"] > 0 else 0
            s["cost_total"] -= avg * sell_shares
            s["shares"] -= sell_shares
            if s["shares"] == 0:
                s["cost_total"] = 0.0
                s["buy_date"] = ""

    out = []
    for sym, s in state.items():
        if s["shares"] > 0:
            out.append({
                "symbol": sym,
                "name": s["name"],
                "shares": s["shares"],
                "cost_price": round(s["cost_total"] / s["shares"], 4),
                "buy_date": s["buy_date"],
            })
    out.sort(key=lambda p: p["symbol"])
    return out


def _sync_positions_cache(state: dict) -> None:
    """从交易流水重算 positions，原子写到 POSITIONS_FILE，供 decision_engine 读"""
    cache = {
        "total_capital": state.get("total_capital", DEFAULT_TOTAL_CAPITAL),
        "positions": derive_positions(state.get("transactions", [])),
    }
    _atomic_write_json(settings.POSITIONS_FILE, cache)


def get_state() -> dict:
    """返回 { total_capital, transactions, positions }（positions 是派生缓存）"""
    with _lock:
        state = _read_transactions()
    return {
        "total_capital": state.get("total_capital", DEFAULT_TOTAL_CAPITAL),
        "transactions": state.get("transactions", []),
        "positions": derive_positions(state.get("transactions", [])),
    }


def set_total_capital(value: float) -> dict:
    if value <= 0:
        raise ValueError("total_capital 必须 > 0")
    with _lock:
        state = _read_transactions()
        state["total_capital"] = float(value)
        _atomic_write_json(settings.TRANSACTIONS_FILE, state)
        _sync_positions_cache(state)
    return get_state()


def add_transaction(tx: dict) -> dict:
    """追加一笔交易；自动生成 id 与 created_at；同步派生 positions。
    必填字段：type(B/S), symbol, shares, price, trade_date
    """
    kind = (tx.get("type") or "").upper()
    if kind not in ("B", "S"):
        raise ValueError("type 必须是 B 或 S")
    symbol = tx.get("symbol") or ""
    if not (isinstance(symbol, str) and symbol.isdigit() and len(symbol) == 6):
        raise ValueError("symbol 必须是 6 位数字")
    shares = int(tx.get("shares") or 0)
    if shares <= 0:
        raise ValueError("shares 必须 > 0")
    price = float(tx.get("price") or 0)
    if price <= 0:
        raise ValueError("price 必须 > 0")
    trade_date = tx.get("trade_date") or ""
    try:
        datetime.strptime(trade_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("trade_date 格式必须是 YYYY-MM-DD")

    record = {
        "id": str(uuid.uuid4())[:8],
        "type": kind,
        "symbol": symbol,
        "name": tx.get("name") or _get_name_map().get(symbol, symbol),
        "shares": shares,
        "price": round(price, 4),
        "trade_date": trade_date,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }

    with _lock:
        state = _read_transactions()
        state.setdefault("transactions", []).append(record)

        # 卖出预校验：不允许卖出超过当前持仓
        if kind == "S":
            positions = derive_positions(state["transactions"][:-1])  # 不含本笔
            holding = next((p for p in positions if p["symbol"] == symbol), None)
            if holding is None or holding["shares"] < shares:
                raise ValueError(
                    f"卖出 {symbol} {shares} 股超过当前持仓 {holding['shares'] if holding else 0} 股"
                )

        _atomic_write_json(settings.TRANSACTIONS_FILE, state)
        _sync_positions_cache(state)

    return record


def delete_transaction(tx_id: str) -> dict:
    """删除指定交易（用于撤销误操作）"""
    with _lock:
        state = _read_transactions()
        before = len(state.get("transactions", []))
        state["transactions"] = [t for t in state.get("transactions", []) if t.get("id") != tx_id]
        if len(state["transactions"]) == before:
            raise ValueError(f"未找到交易 {tx_id}")

        # 校验删除后是否会出现 shares 负数（先卖后买等）
        try:
            derive_positions(state["transactions"])
        except Exception as e:
            raise ValueError(f"删除该交易会导致持仓不一致: {e}")

        _atomic_write_json(settings.TRANSACTIONS_FILE, state)
        _sync_positions_cache(state)
    return get_state()
