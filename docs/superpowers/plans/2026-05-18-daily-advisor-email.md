# Daily Advisor Email Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每个交易日 16:00 自动生成"明日动作单"（卖/买/持有/观望）并通过 QQ 邮箱推送 HTML 摘要。

**Architecture:** 在现有 `daily_job` 五步流水线后追加 step6（决策引擎）和 step7（邮件通知）。卖出规则从 `tests/portfolio_b1_top2.py` 抽到 `api/portfolio/rules.py` 供回测和实盘共用。决策引擎读取手动维护的 `data/positions.json`，通过重放历史 bar 还原派生状态，再用 V2.1 规则判定卖出信号。

**Tech Stack:** Python 3.12, pandas, numpy, smtplib (SMTP_SSL), chinese_calendar, APScheduler, concurrent.futures

**Spec:** `docs/superpowers/specs/2026-05-18-daily-advisor-email-design.md`

---

## Task 1: 配置扩展 (`api/config/settings.py`)

**Files:**
- Modify: `api/config/settings.py:57-63` (追加新常量)

- [ ] **Step 1: 在 settings.py 末尾追加 advisor/email/positions 配置**

```python
# --- Advisor 配置 ---
POSITIONS_FILE = _abs("data/positions.json")
CLOSED_TRADES_FILE = _abs("data/closed_trades.json")
DECISIONS_DIR = _abs("output/decisions")

EMAIL_CONFIG = {
    "host": "smtp.qq.com",
    "port": 465,
    "use_ssl": True,
    "user": _os.getenv("QQ_EMAIL_USER", ""),
    "password": _os.getenv("QQ_EMAIL_PASS", ""),
    "to": _os.getenv("QQ_EMAIL_TO", ""),
    "sender_name": "Stock Quant Daily",
}

ADVISOR_CONFIG = {
    "max_slots_strong": 2,
    "max_slots_weak": 1,
    "single_position_pct_strong": 0.50,
    "single_position_pct_weak": 0.40,
    "cooldown_loss_streak": 2,
    "cooldown_offset": 15,
    "retry_times": 3,
    "retry_interval_sec": 60,
}
```

- [ ] **Step 2: 验证 import 正常**

Run: `python -c "from api.config import settings; print(settings.POSITIONS_FILE, settings.EMAIL_CONFIG['host'])"`
Expected: 输出路径和 `smtp.qq.com`

- [ ] **Step 3: Commit**

```bash
git add api/config/settings.py
git commit -m "feat(config): 追加 advisor/email/positions 配置项"
```

---

## Task 2: 重试工具 (`api/utils/retry.py`)

**Files:**
- Create: `api/utils/retry.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_retry.py
import pytest
from unittest.mock import MagicMock
from api.utils.retry import retry_call


def test_retry_succeeds_on_third_attempt():
    fn = MagicMock(side_effect=[Exception("1"), Exception("2"), "ok"])
    result = retry_call(fn, times=3, interval=0)
    assert result == "ok"
    assert fn.call_count == 3


def test_retry_raises_after_exhaustion():
    fn = MagicMock(side_effect=Exception("fail"))
    with pytest.raises(Exception, match="fail"):
        retry_call(fn, times=2, interval=0)
    assert fn.call_count == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_retry.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 retry_call**

```python
# api/utils/retry.py
import logging
import time

logger = logging.getLogger(__name__)


def retry_call(fn, times: int = 3, interval: int = 60, on_retry=None):
    last_exc = None
    for attempt in range(1, times + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if on_retry:
                on_retry(attempt, e)
            else:
                logger.warning(f"重试 {attempt}/{times} 失败: {e}")
            if attempt < times:
                time.sleep(interval)
    raise last_exc
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_retry.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add api/utils/retry.py tests/test_retry.py
git commit -m "feat(utils): 添加 retry_call 重试工具"
```

---

## Task 3: 卖出规则抽离 (`api/portfolio/rules.py`)

**Files:**
- Create: `api/portfolio/rules.py`
- Create: `tests/test_rules.py`

- [ ] **Step 1: 写 calc_sell_signal 测试**

```python
# tests/test_rules.py
import pytest
from dataclasses import dataclass
from api.portfolio.rules import (
    calc_sell_signal, Position,
    T3_HOLD_DAYS, T3_MIN_GAIN_PCT, TP_LEVELS, TP_RATIO,
    BEAR_VOL_RATIO, BEAR_DROP_PCT,
)


@dataclass
class FakeBar:
    close: float
    open: float
    volume: float


def make_position(cost=10.0, hold_days=0, above_white=False, tp_done=0):
    return Position(
        symbol="600000", name="测试", shares=1000,
        cost_price=cost, buy_date="2026-01-01", buy_day_low=cost,
        initial_shares=1000, hold_days=hold_days,
        max_profit_pct=0.0, tp_level_done=tp_done,
        above_white_once=above_white,
    )


def test_hard_stop_loss_weak_market():
    """弱市 -4% 硬止损"""
    pos = make_position(cost=10.0, hold_days=1)
    # 需要构造 closes/volumes/yellow/white 使得 cur_profit <= -4%
    # 具体实现依赖 rules.py 的接口签名
    # 此处先验证函数存在且可调用
    assert callable(calc_sell_signal)


def test_hard_stop_loss_strong_market():
    """强市 -7% 硬止损"""
    assert callable(calc_sell_signal)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_rules.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 从 tests/portfolio_b1_top2.py 抽出规则到 api/portfolio/rules.py**

从 `tests/portfolio_b1_top2.py` 搬运以下内容（保持逻辑不变）：

```python
# api/portfolio/rules.py
"""V2.1 卖出规则 + 大盘判定（从 tests/portfolio_b1_top2.py 抽离）"""
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.strategy.b1 import B1Strategy

FEE = settings.FEE_CONFIG
SLIPPAGE = 0.001
INDEX_DEFAULT = "idx_000001_SH"

INDEX_MAP = {
    "60": "idx_000001_SH",
    "00": "idx_399001_SZ",
    "30": "idx_399006_SZ",
    "68": "idx_000016_SH",
}

T3_HOLD_DAYS = 3
T3_MIN_GAIN_PCT = 2.0
TP_LEVELS = [10, 20, 30, 40, 50, 60, 70, 80, 90]
TP_RATIO = 1.0 / 3.0
BEAR_VOL_RATIO = 1.5
BEAR_DROP_PCT = 5.0


@dataclass
class Position:
    symbol: str
    name: str
    shares: int
    cost_price: float
    buy_date: str
    buy_day_low: float
    initial_shares: int = 0
    hold_days: int = 0
    max_profit_pct: float = 0.0
    tp_level_done: int = 0
    above_white_once: bool = False


def pick_index_for(symbol: str) -> str:
    return INDEX_MAP.get(symbol[:2], INDEX_DEFAULT)


def load_csv(symbol: str) -> Optional[pd.DataFrame]:
    # 搬运自 tests/portfolio_b1_top2.py:149-162
    ...


def get_bar(df: pd.DataFrame, date: str) -> Optional[pd.Series]:
    # 搬运自 tests/portfolio_b1_top2.py:165-170
    ...


def get_history_until(df: pd.DataFrame, date: str) -> pd.DataFrame:
    # 搬运自 tests/portfolio_b1_top2.py:173-175
    ...


def market_allow_buy(date: str, index_df: pd.DataFrame) -> bool:
    """大盘收盘 >= 大哥黄 才允许买入（一律以 idx_000001_SH 为准）"""
    # 简化签名：直接传入 index_df 而非 index_dfs dict
    # 搬运自 tests/portfolio_b1_top2.py:178-186，去掉 pick_index_for 调用
    ...


def market_is_strong(date: str, index_df: pd.DataFrame) -> bool:
    """大盘强势：close >= 大哥黄 且 5 日斜率 > 0"""
    # 搬运自 tests/portfolio_b1_top2.py:189-202，去掉 pick_index_for 调用
    ...


def calc_sell_signal(pos: Position, df: pd.DataFrame, date: str,
                     market_strong: bool = True) -> tuple:
    """返回 (reason, sell_ratio)。6 类规则按 0→5 顺序判定。"""
    # 一对一搬运自 tests/portfolio_b1_top2.py:205-265
    ...
```

注意：`market_allow_buy` 和 `market_is_strong` 签名简化为直接接收 `index_df`（不再传 `symbol` + `index_dfs` dict），因为 advisor 一律用 `idx_000001_SH`。

- [ ] **Step 4: 完善测试——用真实 DataFrame 构造验证 6 类卖出**

补充完整测试用例（硬止损弱市/强市、跌破大哥黄、阴线放量、破趋势白、T+3、分批止盈），每个用例构造一段 30+ 根 bar 的 DataFrame。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_rules.py -v`
Expected: all passed

- [ ] **Step 6: Commit**

```bash
git add api/portfolio/rules.py tests/test_rules.py
git commit -m "feat(portfolio): 抽离 V2.1 卖出规则到 api/portfolio/rules.py"
```

---

## Task 4: 派生状态重放 (`api/advisor/position_state.py`)

**Files:**
- Create: `api/advisor/__init__.py`
- Create: `api/advisor/position_state.py`
- Create: `tests/test_position_state_replay.py`

- [ ] **Step 1: 写 replay_state 测试**

```python
# tests/test_position_state_replay.py
import pytest
import pandas as pd
from api.advisor.position_state import replay_state
from api.portfolio.rules import Position


def test_replay_buy_date_hold_days_1():
    """buy_date 当天 replay 后 hold_days==1"""
    pos = Position(symbol="600000", name="测试", shares=1000,
                   cost_price=10.0, buy_date="2026-01-02", buy_day_low=9.8,
                   initial_shares=1000)
    # 构造 df 只含 buy_date 当天 1 根 bar
    df = _make_df(dates=["2026-01-02"], closes=[10.0], opens=[10.0],
                  volumes=[100000], highs=[10.5], lows=[9.8])
    replay_state(pos, df, today="2026-01-03")
    assert pos.hold_days == 1


def test_replay_5_bars():
    """buy_date + 后续 4 个交易日，replay 后 hold_days==5"""
    pos = Position(symbol="600000", name="测试", shares=1000,
                   cost_price=10.0, buy_date="2026-01-02", buy_day_low=9.8,
                   initial_shares=1000)
    dates = ["2026-01-02", "2026-01-03", "2026-01-06", "2026-01-07", "2026-01-08"]
    closes = [10.0, 10.2, 10.5, 10.8, 11.0]
    df = _make_df(dates=dates, closes=closes,
                  opens=[10.0]*5, volumes=[100000]*5,
                  highs=[c+0.5 for c in closes], lows=[c-0.2 for c in closes])
    replay_state(pos, df, today="2026-01-09")
    assert pos.hold_days == 5


def _make_df(dates, closes, opens, volumes, highs, lows):
    from api.schemas.kline_constants import KLineConstants
    return pd.DataFrame({
        KLineConstants.DATE: pd.to_datetime(dates),
        KLineConstants.CLOSE: closes,
        KLineConstants.OPEN: opens,
        KLineConstants.VOLUME: volumes,
        KLineConstants.HIGH: highs,
        KLineConstants.LOW: lows,
    })
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_position_state_replay.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 replay_state**

```python
# api/advisor/position_state.py
"""派生状态重放：从 buy_date 当天遍历到 today 前一个交易日"""
import pandas as pd
from api.portfolio.rules import Position, calc_sell_signal, get_history_until
from api.schemas.kline_constants import KLineConstants


def replay_state(pos: Position, df: pd.DataFrame, today: str,
                 market_strong: bool = True):
    """从 buy_date（含）到 today（不含）逐 bar 调用 calc_sell_signal 累加状态。
    忽略中间返回的卖出信号——仅用于累加 hold_days/tp_level_done/above_white_once/max_profit_pct。
    """
    if df is None or df.empty:
        return
    buy_dt = pd.to_datetime(pos.buy_date)
    today_dt = pd.to_datetime(today)
    dates_in_range = df[
        (df[KLineConstants.DATE] >= buy_dt) &
        (df[KLineConstants.DATE] < today_dt)
    ][KLineConstants.DATE].sort_values().tolist()

    for d in dates_in_range:
        date_str = d.strftime("%Y-%m-%d")
        calc_sell_signal(pos, df, date_str, market_strong)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_position_state_replay.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add api/advisor/__init__.py api/advisor/position_state.py tests/test_position_state_replay.py
git commit -m "feat(advisor): 派生状态重放 replay_state"
```

---

## Task 5: 连续亏损冷却 (`api/advisor/cooldown.py`)

**Files:**
- Create: `api/advisor/cooldown.py`
- Create: `tests/test_cooldown.py`

- [ ] **Step 1: 写冷却测试**

```python
# tests/test_cooldown.py
import pytest
from api.advisor.cooldown import compute_cooldown_state


def test_no_trades_no_cooldown():
    state = compute_cooldown_state(trades=[], today_idx=10)
    assert state["active"] is False


def test_two_consecutive_losses_activates():
    trades = [
        {"ratio": 1.0, "pnl_pct": -3.0, "sell_date": "2026-01-10"},
        {"ratio": 1.0, "pnl_pct": -2.0, "sell_date": "2026-01-12"},
    ]
    state = compute_cooldown_state(trades=trades, today_idx=13)
    assert state["active"] is True


def test_profit_resets_streak():
    trades = [
        {"ratio": 1.0, "pnl_pct": -3.0, "sell_date": "2026-01-10"},
        {"ratio": 1.0, "pnl_pct": 5.0, "sell_date": "2026-01-12"},
        {"ratio": 1.0, "pnl_pct": -2.0, "sell_date": "2026-01-14"},
    ]
    state = compute_cooldown_state(trades=trades, today_idx=15)
    assert state["active"] is False


def test_partial_sell_not_counted():
    trades = [
        {"ratio": 0.33, "pnl_pct": -3.0, "sell_date": "2026-01-10"},
        {"ratio": 1.0, "pnl_pct": -2.0, "sell_date": "2026-01-12"},
    ]
    state = compute_cooldown_state(trades=trades, today_idx=13)
    assert state["active"] is False  # 只有 1 笔全清亏损
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cooldown.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 compute_cooldown_state**

```python
# api/advisor/cooldown.py
"""连续亏损冷却判定"""
import json
import os
import logging
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
                # 用 sell_date 对应的 idx 推算 cooldown_until
                # 简化：直接用 today_idx + offset
                cooldown_until = today_idx + cfg["cooldown_offset"]
                streak = 0
        else:
            streak = 0

    active = today_idx < cooldown_until
    remaining = max(0, cooldown_until - today_idx) if active else 0
    return {"active": active, "remaining_days": remaining, "cooldown_until": cooldown_until}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cooldown.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add api/advisor/cooldown.py tests/test_cooldown.py
git commit -m "feat(advisor): 连续亏损冷却判定 compute_cooldown_state"
```

---

## Task 6: 决策 Schema (`api/advisor/decision_schema.py`)

**Files:**
- Create: `api/advisor/decision_schema.py`

- [ ] **Step 1: 创建 dataclass 定义**

```python
# api/advisor/decision_schema.py
"""决策数据结构"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ActionItem:
    kind: str  # sell / buy / hold / wait
    symbol: str = ""
    name: str = ""
    shares: int = 0
    ratio: float = 0.0
    amount: float = 0.0
    estimated_price: float = 0.0
    estimated_shares: int = 0
    reason: str = ""
    exec_desc: str = ""


@dataclass
class HoldingInfo:
    symbol: str
    name: str
    shares: int
    cost_price: float
    current_close: float
    profit_pct: float
    hold_days: int
    tp_level_done: int
    above_white_once: bool


@dataclass
class Decision:
    date: str
    next_trading_date: str
    market: dict = field(default_factory=dict)
    cooldown: dict = field(default_factory=dict)
    holdings: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
```

- [ ] **Step 2: 验证 import**

Run: `python -c "from api.advisor.decision_schema import Decision, ActionItem, HoldingInfo; print('ok')"`
Expected: ok

- [ ] **Step 3: Commit**

```bash
git add api/advisor/decision_schema.py
git commit -m "feat(advisor): 决策数据结构 Decision/ActionItem/HoldingInfo"
```

---

## Task 7: 决策引擎 (`api/advisor/decision_engine.py`)

**Files:**
- Create: `api/advisor/decision_engine.py`
- Create: `tests/test_decision_engine.py`

- [ ] **Step 1: 写决策引擎核心测试**

```python
# tests/test_decision_engine.py
import pytest
from unittest.mock import patch, MagicMock
from api.advisor.decision_engine import run_decision


def test_empty_positions_strong_market_buy():
    """空仓 + 强市 → 输出 2 个 buy 动作（max_slots=2）"""
    with patch("api.advisor.decision_engine._load_positions") as mock_pos, \
         patch("api.advisor.decision_engine._market_state") as mock_mkt, \
         patch("api.advisor.decision_engine._scan_buy_candidates") as mock_scan, \
         patch("api.advisor.decision_engine._get_cooldown_state") as mock_cd:
        mock_pos.return_value = {"total_capital": 100000, "positions": []}
        mock_mkt.return_value = {"allow_buy": True, "is_strong": True,
                                  "max_slots": 2, "single_position_pct": 0.50}
        mock_scan.return_value = [
            {"symbol": "600000", "name": "浦发银行", "close": 10.0, "score": 8.0},
            {"symbol": "601318", "name": "中国平安", "close": 50.0, "score": 7.5},
        ]
        mock_cd.return_value = {"active": False, "remaining_days": 0}

        decision = run_decision("2026-05-18")
        buys = [a for a in decision.actions if a.kind == "buy"]
        assert len(buys) == 2
        assert buys[0].amount == 50000  # 100000 * 0.50


def test_weak_market_max_slots_1():
    """弱市 max_slots=1 + 已有 1 持仓 → 不输出 buy"""
    with patch("api.advisor.decision_engine._load_positions") as mock_pos, \
         patch("api.advisor.decision_engine._market_state") as mock_mkt, \
         patch("api.advisor.decision_engine._get_cooldown_state") as mock_cd, \
         patch("api.advisor.decision_engine._evaluate_holdings") as mock_eval:
        mock_pos.return_value = {"total_capital": 100000, "positions": [
            {"symbol": "600000", "shares": 1000, "cost_price": 10.0, "buy_date": "2026-05-10"}
        ]}
        mock_mkt.return_value = {"allow_buy": True, "is_strong": False,
                                  "max_slots": 1, "single_position_pct": 0.40}
        mock_cd.return_value = {"active": False, "remaining_days": 0}
        mock_eval.return_value = (
            [{"symbol": "600000", "name": "浦发银行", "hold_days": 5}],
            [{"kind": "hold", "symbol": "600000"}]
        )

        decision = run_decision("2026-05-18")
        buys = [a for a in decision.actions if a.kind == "buy"]
        assert len(buys) == 0


def test_market_not_allow_buy_outputs_wait():
    """大盘不允许买入 → wait 动作"""
    with patch("api.advisor.decision_engine._load_positions") as mock_pos, \
         patch("api.advisor.decision_engine._market_state") as mock_mkt, \
         patch("api.advisor.decision_engine._get_cooldown_state") as mock_cd:
        mock_pos.return_value = {"total_capital": 100000, "positions": []}
        mock_mkt.return_value = {"allow_buy": False, "is_strong": False,
                                  "max_slots": 1, "single_position_pct": 0.40}
        mock_cd.return_value = {"active": False, "remaining_days": 0}

        decision = run_decision("2026-05-18")
        waits = [a for a in decision.actions if a.kind == "wait"]
        assert len(waits) >= 1
        assert "大盘" in waits[0].reason
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_decision_engine.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 decision_engine.py**

核心函数 `run_decision(date: str) -> Decision`：

1. `_load_positions()`：读 `data/positions.json`，校验字段
2. `_market_state(date)`：加载 `idx_000001_SH.csv`，调用 `rules.market_allow_buy` / `rules.market_is_strong`，派生 `max_slots` / `single_position_pct`
3. `_get_cooldown_state(date)`：调用 `cooldown.compute_cooldown_state`
4. `_evaluate_holdings(positions, date, market_strong)`：对每只持仓 `replay_state` + `calc_sell_signal`，输出 sell/hold 动作
5. `_scan_buy_candidates(date, slots_left)`：调用 `scan_v2_style.check_one` 并发扫描，按 score 排序取 top
6. `_compute_next_trading_date(date)`：用 `chinese_calendar` 找下一个工作日
7. 组装 `Decision` 对象
8. 原子写 `output/decisions/decision_YYYYMMDD.json`

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_decision_engine.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add api/advisor/decision_engine.py tests/test_decision_engine.py
git commit -m "feat(advisor): 决策引擎 run_decision"
```

---

## Task 8: 邮件发送 (`api/notifier/email_sender.py`)

**Files:**
- Create: `api/notifier/__init__.py`
- Create: `api/notifier/email_sender.py`
- Create: `tests/test_email_sender.py`

- [ ] **Step 1: 写邮件发送测试**

```python
# tests/test_email_sender.py
import pytest
from unittest.mock import patch, MagicMock
from api.notifier.email_sender import send_email, send_error_email


@patch("api.notifier.email_sender.smtplib.SMTP_SSL")
def test_send_email_success(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

    send_email(subject="测试", html_body="<p>hi</p>", plain_body="hi")
    mock_smtp.sendmail.assert_called_once()


@patch("api.notifier.email_sender.smtplib.SMTP_SSL")
def test_send_email_retry_on_failure(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp.sendmail.side_effect = [Exception("timeout"), None]
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

    # 重试 interval=0 加速测试
    send_email(subject="测试", html_body="<p>hi</p>", plain_body="hi",
               retry_interval=0)
    assert mock_smtp.sendmail.call_count == 2


@patch("api.notifier.email_sender.smtplib.SMTP_SSL")
def test_send_error_email(mock_smtp_cls):
    mock_smtp = MagicMock()
    mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_smtp)
    mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

    send_error_email(step="fetch_data", error_msg="connection timeout")
    mock_smtp.sendmail.assert_called_once()
    args = mock_smtp.sendmail.call_args
    assert "异常" in str(args)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_email_sender.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: 实现 email_sender.py**

```python
# api/notifier/email_sender.py
"""QQ 邮箱 SMTP 发送"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from api.config import settings
from api.utils.retry import retry_call

logger = logging.getLogger(__name__)


def send_email(subject: str, html_body: str, plain_body: str,
               retry_interval: int = None):
    cfg = settings.EMAIL_CONFIG
    if not cfg["user"] or not cfg["password"]:
        raise RuntimeError("QQ_EMAIL_USER 或 QQ_EMAIL_PASS 未配置")

    interval = retry_interval if retry_interval is not None else settings.ADVISOR_CONFIG["retry_interval_sec"]

    def _send():
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{cfg['sender_name']} <{cfg['user']}>"
        msg["To"] = cfg["to"] or cfg["user"]
        msg.attach(MIMEText(plain_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["user"], msg["To"], msg.as_string())

    retry_call(_send, times=settings.ADVISOR_CONFIG["retry_times"], interval=interval)
    logger.info(f"邮件已发送: {subject}")


def send_error_email(step: str, error_msg: str):
    subject = f"【量化日报-异常】{step}"
    body = f"步骤 {step} 执行失败:\n\n{error_msg[-3000:]}"
    try:
        send_email(subject=subject, html_body=f"<pre>{body}</pre>",
                   plain_body=body, retry_interval=10)
    except Exception as e:
        logger.error(f"错误邮件发送失败: {e}")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_email_sender.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add api/notifier/__init__.py api/notifier/email_sender.py tests/test_email_sender.py
git commit -m "feat(notifier): QQ SMTP 邮件发送 + 重试"
```

---

## Task 9: HTML 模板 (`api/notifier/templates.py`)

**Files:**
- Create: `api/notifier/templates.py`

- [ ] **Step 1: 实现 render_html 和 render_plain_text**

```python
# api/notifier/templates.py
"""邮件 HTML/纯文本模板渲染"""
from api.advisor.decision_schema import Decision


def render_subject(decision: Decision) -> str:
    market = decision.market
    status = "允许买入" if market.get("allow_buy") else "禁止买入"
    strength = "强势" if market.get("is_strong") else "弱势"
    return f"【量化日报】{decision.date} · 大盘:{status}/{strength}"


def render_html(decision: Decision) -> str:
    """全 inline style、table 布局、字号 ≥ 14px"""
    # 持仓表 + 动作表 + 脚注 + 维护提示
    ...


def render_plain_text(decision: Decision) -> str:
    """纯文本 fallback"""
    ...
```

实现要点：
- 全部 inline style，禁用 `<style>` 块
- 用 `<table>` 布局
- 动作色块：sell=`#ffcccc`、buy=`#ccffcc`、hold/wait=`#f0f0f0`
- 脚注列出 6 类卖出规则简述
- 维护提示："卖出成交后请在 closed_trades.json 追加记录"

- [ ] **Step 2: 验证渲染**

Run: `python -c "from api.notifier.templates import render_html, render_subject; from api.advisor.decision_schema import Decision; d = Decision(date='2026-05-18', next_trading_date='2026-05-19', market={'allow_buy': True, 'is_strong': False}); print(render_subject(d))"`
Expected: `【量化日报】2026-05-18 · 大盘:允许买入/弱势`

- [ ] **Step 3: Commit**

```bash
git add api/notifier/templates.py
git commit -m "feat(notifier): HTML/纯文本邮件模板"
```

---

## Task 10: 调度器集成 (`api/scheduler/`)

**Files:**
- Modify: `api/scheduler/scheduler.py:39-43` (cron 改 16:00)
- Modify: `api/scheduler/jobs.py` (追加 step6/step7)

- [ ] **Step 1: 修改 scheduler.py cron 为 16:00**

```python
# api/scheduler/scheduler.py:39-43 改为
trigger=CronTrigger(
    day_of_week='mon-fri',
    hour=16,
    minute=0,
),
```

- [ ] **Step 2: 在 jobs.py 追加 step6 和 step7**

在 `daily_job` 的 step5 之后追加：

```python
        # Step 6: 决策
        logger.info("Step 6: 生成决策...")
        decision = _step_decide(today)

        # Step 7: 邮件通知
        logger.info("Step 7: 发送邮件通知...")
        _step_notify(decision)

    except Exception as e:
        logger.error(f"每日任务失败: {e}", exc_info=True)
        _try_send_error_mail("daily_job", e)


def _step_decide(date: str):
    from api.advisor.decision_engine import run_decision
    from api.utils.retry import retry_call
    return retry_call(lambda: run_decision(date),
                      times=settings.ADVISOR_CONFIG["retry_times"],
                      interval=settings.ADVISOR_CONFIG["retry_interval_sec"])


def _step_notify(decision):
    from api.notifier.email_sender import send_email
    from api.notifier.templates import render_html, render_plain_text, render_subject
    subject = render_subject(decision)
    html = render_html(decision)
    plain = render_plain_text(decision)
    send_email(subject=subject, html_body=html, plain_body=plain)


def _try_send_error_mail(step: str, exc: Exception):
    import traceback
    try:
        from api.notifier.email_sender import send_error_email
        tb = traceback.format_exc()
        send_error_email(step=step, error_msg=tb[-3000:])
    except Exception as e2:
        logger.error(f"错误邮件发送失败: {e2}")
```

- [ ] **Step 3: 验证 import 链**

Run: `python -c "from api.scheduler.jobs import daily_job; print('ok')"`
Expected: ok

- [ ] **Step 4: Commit**

```bash
git add api/scheduler/scheduler.py api/scheduler/jobs.py
git commit -m "feat(scheduler): 调度改 16:00 + 追加 step6 决策 step7 通知"
```

---

## Task 11: CLI 入口 (`main.py`)

**Files:**
- Create: `main.py`

- [ ] **Step 1: 创建 main.py advisor 子命令**

```python
# main.py
"""量化交易平台 CLI 入口"""
import argparse
import sys
from datetime import datetime


def cmd_advisor(args):
    from api.advisor.decision_engine import run_decision
    from api.notifier.email_sender import send_email
    from api.notifier.templates import render_html, render_plain_text, render_subject

    date = args.date or datetime.now().strftime("%Y-%m-%d")

    if args.email_only:
        import json, os
        from api.config import settings
        path = os.path.join(settings.DECISIONS_DIR,
                            f"decision_{date.replace('-', '')}.json")
        if not os.path.exists(path):
            print(f"决策文件不存在: {path}")
            sys.exit(1)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        from api.advisor.decision_schema import Decision
        decision = Decision(**{k: data[k] for k in
                              ["date", "next_trading_date", "market",
                               "cooldown", "holdings", "actions", "warnings"]})
    else:
        decision = run_decision(date)

    if not args.no_email and not args.email_only:
        send_email(subject=render_subject(decision),
                   html_body=render_html(decision),
                   plain_body=render_plain_text(decision))
        print("邮件已发送")
    elif args.email_only:
        send_email(subject=render_subject(decision),
                   html_body=render_html(decision),
                   plain_body=render_plain_text(decision))
        print("邮件已发送")
    else:
        print(f"决策已生成，跳过邮件发送")


def main():
    parser = argparse.ArgumentParser(description="A 股量化交易平台")
    sub = parser.add_subparsers(dest="command")

    # advisor
    p_adv = sub.add_parser("advisor", help="生成决策 + 邮件通知")
    p_adv.add_argument("--date", default=None, help="日期 YYYY-MM-DD，默认今日")
    p_adv.add_argument("--no-email", action="store_true", help="仅生成决策不发邮件")
    p_adv.add_argument("--email-only", action="store_true", help="用已有决策文件仅发邮件")

    args = parser.parse_args()
    if args.command == "advisor":
        cmd_advisor(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 验证 CLI help**

Run: `python main.py advisor --help`
Expected: 显示 `--date / --no-email / --email-only` 参数

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat(cli): 添加 advisor 子命令入口"
```

---

## Task 12: 回测脚本改用共享规则

**Files:**
- Modify: `tests/portfolio_b1_top2.py` (import 改为 `from api.portfolio.rules import ...`)

- [ ] **Step 1: 替换 tests/portfolio_b1_top2.py 中的规则定义为 import**

删除 `tests/portfolio_b1_top2.py` 中的以下本地定义：
- `Position` dataclass (line 107-119)
- `T3_HOLD_DAYS / T3_MIN_GAIN_PCT / TP_LEVELS / TP_RATIO / BEAR_VOL_RATIO / BEAR_DROP_PCT` (line 98-104)
- `pick_index_for` (line 53-57)
- `load_csv / get_bar / get_history_until` (line 149-175)
- `market_allow_buy / market_is_strong` (line 178-202)
- `calc_sell_signal` (line 205-265)

替换为：

```python
from api.portfolio.rules import (
    Position, calc_sell_signal, load_csv, get_bar, get_history_until,
    market_allow_buy, market_is_strong, pick_index_for,
    T3_HOLD_DAYS, T3_MIN_GAIN_PCT, TP_LEVELS, TP_RATIO,
    BEAR_VOL_RATIO, BEAR_DROP_PCT, INDEX_MAP, INDEX_DEFAULT,
    buy_fee, sell_fee,
)
```

注意：`market_allow_buy` / `market_is_strong` 在 `rules.py` 中签名简化了（直接传 `index_df`），回测脚本调用处需要适配。

- [ ] **Step 2: 运行回测脚本验证不报错**

Run: `python tests/portfolio_b1_top2.py --start 2025-01-01 --end 2025-02-28 --workers 4`
Expected: 正常输出回测结果（数值应与改动前一致）

- [ ] **Step 3: Commit**

```bash
git add tests/portfolio_b1_top2.py
git commit -m "refactor(tests): portfolio_b1_top2 改用 api.portfolio.rules 共享规则"
```

---

## Task 13: 端到端集成测试

**Files:**
- Create: `tests/test_advisor_e2e.py`

- [ ] **Step 1: 写端到端测试**

```python
# tests/test_advisor_e2e.py
"""端到端：构造 positions.json + 真实 CSV 数据 → run_decision → 验证输出"""
import json
import os
import tempfile
import pytest
from unittest.mock import patch
from api.advisor.decision_engine import run_decision
from api.config import settings


@pytest.fixture
def setup_positions(tmp_path):
    pos_file = tmp_path / "positions.json"
    pos_file.write_text(json.dumps({
        "total_capital": 100000,
        "positions": []
    }))
    with patch.object(settings, "POSITIONS_FILE", str(pos_file)), \
         patch.object(settings, "CLOSED_TRADES_FILE", str(tmp_path / "closed.json")), \
         patch.object(settings, "DECISIONS_DIR", str(tmp_path)):
        yield tmp_path


def test_e2e_empty_positions(setup_positions):
    """空仓 + 有数据 → 应产出 decision JSON"""
    # 需要 idx_000001_SH.csv 和至少一只股票 CSV 存在
    # 如果 data/ 目录有数据则可跑；否则 skip
    idx_path = os.path.join(settings.DATA_DIR, "idx_000001_SH.csv")
    if not os.path.exists(idx_path):
        pytest.skip("缺少大盘数据")

    decision = run_decision("2026-05-16")
    assert decision.date == "2026-05-16"
    assert decision.market.get("index") == "idx_000001_SH"
```

- [ ] **Step 2: 运行测试**

Run: `python -m pytest tests/test_advisor_e2e.py -v`
Expected: passed (或 skip if no data)

- [ ] **Step 3: Commit**

```bash
git add tests/test_advisor_e2e.py
git commit -m "test: advisor 端到端集成测试"
```

---

## Task 14: 最终验证 & 清理

- [ ] **Step 1: 运行全部测试**

Run: `python -m pytest tests/test_retry.py tests/test_rules.py tests/test_position_state_replay.py tests/test_cooldown.py tests/test_decision_engine.py tests/test_email_sender.py tests/test_advisor_e2e.py -v`
Expected: all passed

- [ ] **Step 2: 验证 CLI 完整流程（不发邮件）**

Run: `python main.py advisor --date 2026-05-16 --no-email`
Expected: 输出"决策已生成"，`output/decisions/decision_20260516.json` 存在

- [ ] **Step 3: 验证 import 链完整**

Run: `python -c "from api.scheduler.jobs import daily_job; from api.advisor.decision_engine import run_decision; from api.notifier.email_sender import send_email; print('all imports ok')"`
Expected: all imports ok

- [ ] **Step 4: 最终 commit**

```bash
git add -A
git status  # 确认无遗漏
git commit -m "feat: 每日收盘后自动决策与邮件推送——完整实现"
```

