"""
v_master 策略
底部巨量 → 洗盘不破 → 二次启动放量 买入策略

买入条件（全部硬规则，无打分）:
  1. 翻番过滤：近 60 日 max/min ≥ 1.8 跳过
  2. 巨量基础日 V_idx（V 锚）：在 [T-cooldown_max, T-cooldown_min] 窗口内最早
     满足以下的 i
       a) 下跌语境：closes[i] ≤ max(highs[i-down_lookback..i-1]) × (1 - down_drawdown%)
       b) 阳线：closes[i] > opens[i] 且实体涨幅 ≥ v_body_min_pct（30/68 用 v_body_min_pct_kc）
       c) 巨量：volumes[i] / mean(volumes[i-5..i-1]) ≥ v_vol_ratio
       d) 不能涨停（< 板块限制 - 0.1）
  3. 洗盘期 [V_idx+1..T-1]：
       a) 不破巨量低点：min(lows) ≥ lows[V_idx]
       b) 无放量大阴：任一 j 跌幅 > 5% 且量比 > 1.5 → 淘汰
  4. 决策日 T：
       a) 阳线，涨幅 ≥ t_body_min_pct（30/68 用 t_body_min_pct_kc）
       b) 量比 ≥ t_vol_ratio
       c) 收盘 ≥ MA5
       d) 量能重心上移：mean(volumes[T-4..T]) > mean(volumes[V_idx-20..V_idx-1])
       e) MA10 > MA20 且 MA10[T] > MA10[T-1]（拐头向上）
       f) 不能涨停

卖出条件（仅一条铁律）:
  bar.close < v_low（V 锚日最低价）→ 全仓清出

无放飞减仓、无回撤止盈、无时间止损。
"""
from collections import deque

import numpy as np
from vnpy.trader.object import BarData

from api.strategy.base_strategy import BaseStrategy


class VMasterStrategy(BaseStrategy):
    """v_master 策略：底部巨量 + 洗盘不破 + 二次启动"""

    author = "stock_quant"

    # === V 锚（巨量基础日）参数 ===
    lookback_v = 60                 # 找 V 锚的回看天数
    cooldown_min = 5                # V 与 T 至少间隔
    cooldown_max = 15               # V 与 T 最多间隔
    down_lookback = 60              # 下跌语境的高点回看
    down_drawdown = 20.0            # 下跌幅度阈值（%）
    v_body_min_pct = 3.0            # V 锚阳线最小实体涨幅（主板）
    v_body_min_pct_kc = 4.0         # 创/科/北板 V 锚阳线最小实体涨幅
    v_vol_ratio = 3.0               # V 锚量比阈值（基准 5 日均量）

    # === 洗盘期参数 ===
    washout_drop_pct = 5.0          # 洗盘期放量大阴阈值
    washout_drop_vol_ratio = 1.5    # 洗盘期放量大阴量比

    # === 决策日 T 参数 ===
    t_body_min_pct = 2.0            # 决策日阳线涨幅（主板）
    t_body_min_pct_kc = 2.5         # 决策日阳线涨幅（创/科/北）
    t_vol_ratio = 1.5               # 决策日量比阈值

    # === 入场前置过滤 ===
    doubled_lookback = 60
    doubled_ratio = 1.8

    parameters = [
        "lookback_v", "cooldown_min", "cooldown_max",
        "down_lookback", "down_drawdown",
        "v_body_min_pct", "v_body_min_pct_kc", "v_vol_ratio",
        "washout_drop_pct", "washout_drop_vol_ratio",
        "t_body_min_pct", "t_body_min_pct_kc", "t_vol_ratio",
        "doubled_lookback", "doubled_ratio",
    ]
    variables = ["v_low", "v_idx_date", "buy_price"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.v_low = 0.0
        self.v_idx_date = ""
        self.buy_price = 0.0
        self._pending_v_low = 0.0
        self._pending_v_idx_date = ""
        # 与 am.close_array 等长，索引一一对齐；预热前用空串占位
        self._dt_buf: deque = deque(["" for _ in range(self.am.size)],
                                    maxlen=self.am.size)

    # ------------------------------------------------------------------
    # 数据维护
    # ------------------------------------------------------------------
    def on_bar(self, bar: BarData):
        # 先把 datetime 推入 buf，与 am.update_bar 同步左移；这样在 execute_logic 里
        # _dt_buf[i] 与 close_array[i] 永远一一对应
        self._dt_buf.append(bar.datetime.date().isoformat())
        super().on_bar(bar)

    @staticmethod
    def _is_kc_board(symbol: str) -> bool:
        """30 / 68 / 8 开头的板块阳线门槛更高（涨跌停 ±20%）"""
        return symbol.startswith("30") or symbol.startswith("68") or symbol.startswith("8")

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        am = self.am
        opens = am.open_array
        highs = am.high_array
        lows = am.low_array
        closes = am.close_array
        volumes = am.volume_array
        n_total = len(closes)
        T = n_total - 1
        symbol = self.vt_symbol.split(".")[0]
        is_kc = self._is_kc_board(symbol)

        # ========== 卖出 ==========
        if self.pos > 0:
            if can_sell and not at_lower_limit and self.v_low > 0:
                if bar.close_price < self.v_low:
                    reason = f"破V锚低点{self.v_low:.2f}"
                    self.sell_stock(bar.close_price, abs(self.pos), reason=reason)
            return

        # ========== 买入 ==========
        if at_upper_limit:
            return

        if self._recently_doubled(closes):
            return

        v_idx = self._find_v_anchor(
            opens, highs, lows, closes, volumes, T,
            lookback_v=self.lookback_v,
            cooldown_min=self.cooldown_min,
            cooldown_max=self.cooldown_max,
            down_lookback=self.down_lookback,
            down_drawdown=self.down_drawdown,
            v_body_min_pct=self.v_body_min_pct_kc if is_kc else self.v_body_min_pct,
            v_vol_ratio=self.v_vol_ratio,
            limit_rate=self._get_limit_rate(),
        )
        if v_idx is None:
            return

        if not self._check_washout(
            opens, closes, lows, volumes, v_idx, T,
            washout_drop_pct=self.washout_drop_pct,
            washout_drop_vol_ratio=self.washout_drop_vol_ratio,
        ):
            return

        ok, today_vr, ma5, ma10, ma20 = self._check_today_confirm(
            opens, closes, volumes, v_idx, T,
            t_body_min_pct=self.t_body_min_pct_kc if is_kc else self.t_body_min_pct,
            t_vol_ratio=self.t_vol_ratio,
            limit_rate=self._get_limit_rate(),
        )
        if not ok:
            return

        # 暂存 V 信息，T+1 成交回调里固化
        self._pending_v_low = float(lows[v_idx])
        self._pending_v_idx_date = self._dt_buf[v_idx] or ""
        v_vr = self._vol_ratio(volumes, v_idx)
        center_ratio = self._volume_center_ratio(volumes, v_idx, T)
        reason = (f"v_master[V={self._pending_v_idx_date} V量比{v_vr:.1f} "
                  f"今量比{today_vr:.1f} 量重移{center_ratio:.2f}x]")
        self.buy_full(bar.close_price, reason=reason)

    # ------------------------------------------------------------------
    # 成交回调
    # ------------------------------------------------------------------
    def on_trade(self, trade):
        super().on_trade(trade)
        if trade.direction.value == "多":
            self.buy_price = float(trade.price)
            self.v_low = self._pending_v_low
            self.v_idx_date = self._pending_v_idx_date
            self._pending_v_low = 0.0
            self._pending_v_idx_date = ""
        else:
            self.v_low = 0.0
            self.v_idx_date = ""
            self.buy_price = 0.0
            self._pending_v_low = 0.0
            self._pending_v_idx_date = ""

    # ------------------------------------------------------------------
    # 私有助手（实例方法，依赖类参数）
    # ------------------------------------------------------------------
    def _recently_doubled(self, closes: np.ndarray) -> bool:
        n = self.doubled_lookback
        if n <= 0 or len(closes) < n:
            return False
        window = closes[-n:]
        win_low = float(np.min(window))
        if win_low <= 0:
            return False
        win_high = float(np.max(window))
        return win_high / win_low >= self.doubled_ratio

    # ------------------------------------------------------------------
    # 静态判定函数（策略层 + 扫描器共用，签名统一接收 numpy 数组）
    # ------------------------------------------------------------------
    @staticmethod
    def min_bars_required(lookback_v: int = 60, down_lookback: int = 60) -> int:
        """数据下限：V 锚需要 lookback_v 之前的 down_lookback 高点 + 5 日量基线 + 余量"""
        return max(lookback_v + 25, down_lookback + 20)

    @staticmethod
    def _vol_ratio(volumes: np.ndarray, i: int, window: int = 5) -> float:
        if i < window:
            return 0.0
        base = float(np.mean(volumes[i - window:i]))
        return float(volumes[i] / base) if base > 0 else 0.0

    @staticmethod
    def _ma(closes: np.ndarray, i: int, period: int) -> float:
        if i + 1 < period:
            return 0.0
        return float(np.mean(closes[i + 1 - period:i + 1]))

    @staticmethod
    def _volume_center_ratio(volumes: np.ndarray, v_idx: int, T: int) -> float:
        """决策日近 5 日均量 / V 锚之前 20 日均量"""
        if v_idx < 20 or T < 4:
            return 0.0
        base = float(np.mean(volumes[v_idx - 20:v_idx]))
        if base <= 0:
            return 0.0
        recent = float(np.mean(volumes[T - 4:T + 1]))
        return recent / base

    @staticmethod
    def _find_v_anchor(opens: np.ndarray, highs: np.ndarray, lows: np.ndarray,
                       closes: np.ndarray, volumes: np.ndarray, T: int,
                       *,
                       lookback_v: int, cooldown_min: int, cooldown_max: int,
                       down_lookback: int, down_drawdown: float,
                       v_body_min_pct: float, v_vol_ratio: float,
                       limit_rate: float):
        """在 [T-cooldown_max, T-cooldown_min] 窗口内找最早的 V 锚 idx；找不到返回 None。"""
        n_total = len(closes)
        min_required = max(lookback_v + 25, down_lookback + 20)
        if n_total < min_required or T <= 0:
            return None

        lo = max(down_lookback, T - cooldown_max, T - lookback_v)
        hi = T - cooldown_min  # 闭区间上界
        if lo > hi:
            return None

        limit_threshold = limit_rate * 100 - 0.1  # 涨停判定（百分比）

        for i in range(lo, hi + 1):
            o = float(opens[i]); c = float(closes[i])
            if o <= 0 or c <= 0:
                continue
            # b) 阳线 + 实体涨幅
            if c <= o:
                continue
            body_pct = (c - o) / o * 100
            if body_pct < v_body_min_pct:
                continue
            # d) 不能涨停（按昨收）
            if i >= 1 and closes[i - 1] > 0:
                day_pct = (c - float(closes[i - 1])) / float(closes[i - 1]) * 100
                if day_pct >= limit_threshold:
                    continue
            # a) 下跌语境
            high_window_lo = i - down_lookback
            if high_window_lo < 0:
                continue
            prev_high = float(np.max(highs[high_window_lo:i]))
            if prev_high <= 0:
                continue
            if c > prev_high * (1 - down_drawdown / 100.0):
                continue
            # c) 巨量
            vr = VMasterStrategy._vol_ratio(volumes, i)
            if vr < v_vol_ratio:
                continue
            return i
        return None

    @staticmethod
    def _check_washout(opens: np.ndarray, closes: np.ndarray, lows: np.ndarray,
                       volumes: np.ndarray, v_idx: int, T: int,
                       *,
                       washout_drop_pct: float,
                       washout_drop_vol_ratio: float) -> bool:
        """洗盘期 [v_idx+1..T-1]：不破 v_idx 低点 + 无放量大阴。"""
        if T - v_idx < 2:
            # 至少要有 1 根洗盘 bar
            return False
        v_low = float(lows[v_idx])
        if v_low <= 0:
            return False
        for j in range(v_idx + 1, T):
            if float(lows[j]) < v_low:
                return False
            o = float(opens[j]); c = float(closes[j])
            if o <= 0:
                continue
            drop_pct = (o - c) / o * 100  # 阴线为正
            if drop_pct > washout_drop_pct:
                vr = VMasterStrategy._vol_ratio(volumes, j)
                if vr > washout_drop_vol_ratio:
                    return False
        return True

    @staticmethod
    def _check_today_confirm(opens: np.ndarray, closes: np.ndarray,
                             volumes: np.ndarray, v_idx: int, T: int,
                             *,
                             t_body_min_pct: float, t_vol_ratio: float,
                             limit_rate: float):
        """决策日 T 二次启动确认。返回 (ok, today_vol_ratio, ma5, ma10, ma20)。"""
        zero = (False, 0.0, 0.0, 0.0, 0.0)
        if T < 20:
            return zero
        o = float(opens[T]); c = float(closes[T])
        if o <= 0 or c <= 0:
            return zero
        # a) 阳线 + 涨幅
        if c <= o:
            return zero
        body_pct = (c - o) / o * 100
        if body_pct < t_body_min_pct:
            return zero
        # f) 不能涨停（按昨收）
        if T >= 1 and closes[T - 1] > 0:
            day_pct = (c - float(closes[T - 1])) / float(closes[T - 1]) * 100
            if day_pct >= limit_rate * 100 - 0.1:
                return zero
        # b) 量比
        today_vr = VMasterStrategy._vol_ratio(volumes, T)
        if today_vr < t_vol_ratio:
            return zero
        # c) 站上 MA5
        ma5 = VMasterStrategy._ma(closes, T, 5)
        if ma5 <= 0 or c < ma5:
            return zero
        # d) 量能重心上移
        center = VMasterStrategy._volume_center_ratio(volumes, v_idx, T)
        if center <= 1.0:
            return zero
        # e) 均线翻多 + MA10 拐头向上
        ma10 = VMasterStrategy._ma(closes, T, 10)
        ma20 = VMasterStrategy._ma(closes, T, 20)
        ma10_prev = VMasterStrategy._ma(closes, T - 1, 10)
        if ma10 <= 0 or ma20 <= 0 or ma10_prev <= 0:
            return zero
        if not (ma10 > ma20 and ma10 > ma10_prev):
            return zero
        return True, today_vr, ma5, ma10, ma20
