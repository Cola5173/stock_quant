"""
v_master 策略：主力进场识别

信号链：
  1. MACD 底背离（DIF 底背离 或 MACD 柱底背离，任一成立）
  2. 量能放大事件（近 30 日内存在某日量比 ≥ vol_surge_ratio）
  3. DIF 从水下转水上（DIF > 0）
  4. 收盘站稳黄白线上方（close > 大哥黄 且 close > 趋势白）
  → 满仓买入

止损：
  close < min(大哥黄, 趋势白) → 全仓清出

核心理念：量能骗不了人。股价长期阴跌/横盘后，主力进场必然带来量能异常放大。
MACD 底背离确认下跌动能衰竭，量能放大确认主力入场，DIF 水上 + 站稳黄白确认趋势反转。
"""
from collections import deque

import numpy as np
from vnpy.trader.object import BarData

from api.strategy.base_strategy import BaseStrategy


class VMasterStrategy(BaseStrategy):
    """v_master 策略：MACD 底背离 + 量能放大 + DIF 水上 + 站稳黄白线"""

    author = "stock_quant"

    # === MACD 底背离参数 ===
    divergence_lookback = 60        # 底背离回看窗口（交易日）
    divergence_min_gap = 5          # 两个低点之间最小间隔

    # === 量能放大参数 ===
    vol_surge_lookback = 30         # 量能放大事件回看窗口
    vol_surge_ratio = 2.0           # 量能放大阈值（基于该日前 20 日均量）
    vol_base_window = 20            # 量能基线窗口

    # === 入场前置过滤 ===
    doubled_lookback = 60
    doubled_ratio = 1.8

    # === 止盈止损参数 ===
    big_bull_pct = 4.0              # 中大阳阈值（涨幅 %）
    big_bull_sell_ratio = 0.3       # 中大阳卖出比例（0.3 = 30%）
    white_break_days = 2            # 跌破白线连续天数

    # === 黄白线参数（与 indicators.py 一致） ===
    # 趋势白 = EMA(EMA(C,10),10)
    # 大哥黄 = (MA14 + MA28 + MA57 + MA114) / 4

    parameters = [
        "divergence_lookback", "divergence_min_gap",
        "vol_surge_lookback", "vol_surge_ratio", "vol_base_window",
        "doubled_lookback", "doubled_ratio",
        "big_bull_pct", "big_bull_sell_ratio", "white_break_days",
    ]
    variables = ["buy_price", "white_break_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.buy_price = 0.0
        self.white_break_count = 0  # 跌破白线连续天数计数器
        # 与 am.close_array 等长，索引一一对齐
        self._dt_buf: deque = deque(["" for _ in range(self.am.size)],
                                    maxlen=self.am.size)

    # ------------------------------------------------------------------
    # 数据维护
    # ------------------------------------------------------------------
    def on_bar(self, bar: BarData):
        self._dt_buf.append(bar.datetime.date().isoformat())
        super().on_bar(bar)

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        am = self.am
        closes = am.close_array
        volumes = am.volume_array
        T = len(closes) - 1

        # ========== 卖出 ==========
        if self.pos > 0:
            if can_sell and not at_lower_limit:
                white = self._calc_white(closes, T)

                # 1. 中大阳分批止盈
                if T >= 1 and closes[T - 1] > 0:
                    day_chg = (bar.close_price - float(closes[T - 1])) / float(closes[T - 1]) * 100
                    is_bull = bar.close_price > bar.open_price
                    if is_bull and day_chg >= self.big_bull_pct:
                        sell_vol = int(abs(self.pos) * self.big_bull_sell_ratio)
                        if sell_vol > 0:
                            reason = f"中大阳放飞{self.big_bull_sell_ratio*100:.0f}%(涨{day_chg:.1f}%)"
                            self.sell_stock(bar.close_price, sell_vol, reason=reason)
                            # 重置跌破计数器（止盈后重新计数）
                            self.white_break_count = 0
                            return

                # 2. 连续 N 天跌破白线止损
                if white > 0:
                    if bar.close_price < white:
                        self.white_break_count += 1
                        if self.white_break_count >= self.white_break_days:
                            reason = f"连续{self.white_break_days}天跌破白线(白{white:.2f})"
                            self.sell_stock(bar.close_price, abs(self.pos), reason=reason)
                    else:
                        # 重新站上白线，重置计数器
                        self.white_break_count = 0
            return

        # ========== 买入 ==========
        if at_upper_limit:
            return

        # 前置过滤：翻番
        if self._recently_doubled(closes):
            return

        # 数据充足性检查
        min_required = self.divergence_lookback + 30
        count = int(am.count)
        if count < min_required:
            return

        # 1. MACD 底背离
        dif, dea, macd_bar = self._calc_macd(closes)
        if not self._has_bottom_divergence(
            closes, dif, macd_bar, T,
            lookback=self.divergence_lookback,
            min_gap=self.divergence_min_gap,
        ):
            return

        # 2. 量能放大事件
        if not self._has_volume_surge(
            volumes, T,
            lookback=self.vol_surge_lookback,
            ratio=self.vol_surge_ratio,
            base_window=self.vol_base_window,
        ):
            return

        # 3. DIF 水上
        if dif[T] <= 0:
            return

        # 4. 站稳黄白线
        yellow = self._calc_yellow(closes, T)
        white = self._calc_white(closes, T)
        if yellow <= 0 or white <= 0:
            return
        if bar.close_price <= yellow or bar.close_price <= white:
            return

        # 5. 不能涨停
        if T >= 1 and closes[T - 1] > 0:
            limit = self._get_limit_rate()
            day_pct = (bar.close_price - float(closes[T - 1])) / float(closes[T - 1])
            if day_pct >= limit - 0.001:
                return

        # 入场
        reason = (f"v_master[底背离+量能放大+DIF水上+站稳黄白 "
                  f"DIF={dif[T]:.2f} 黄={yellow:.2f} 白={white:.2f}]")
        self.buy_full(bar.close_price, reason)

    # ------------------------------------------------------------------
    # on_trade 覆盖
    # ------------------------------------------------------------------
    def on_trade(self, trade):
        super().on_trade(trade)
        is_buy = trade.direction.value == "多"
        if is_buy:
            self.buy_price = trade.price
            self.white_break_count = 0
        else:
            # 如果是全部清仓，重置状态
            if self.pos == 0:
                self.buy_price = 0.0
                self.white_break_count = 0

    # ------------------------------------------------------------------
    # MACD 计算
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_macd(closes: np.ndarray):
        """计算 MACD 三件套，返回 (dif, dea, macd_bar) 全长度数组。"""
        n = len(closes)
        ema12 = np.zeros(n)
        ema26 = np.zeros(n)
        ema12[0] = closes[0]
        ema26[0] = closes[0]
        m12 = 2.0 / 13.0
        m26 = 2.0 / 27.0
        for i in range(1, n):
            ema12[i] = ema12[i - 1] + m12 * (closes[i] - ema12[i - 1])
            ema26[i] = ema26[i - 1] + m26 * (closes[i] - ema26[i - 1])
        dif = ema12 - ema26
        dea = np.zeros(n)
        dea[0] = dif[0]
        m9 = 2.0 / 10.0
        for i in range(1, n):
            dea[i] = dea[i - 1] + m9 * (dif[i] - dea[i - 1])
        macd_bar = (dif - dea) * 2
        return dif, dea, macd_bar

    # ------------------------------------------------------------------
    # MACD 底背离判定
    # ------------------------------------------------------------------
    @staticmethod
    def _has_bottom_divergence(closes: np.ndarray, dif: np.ndarray,
                               macd_bar: np.ndarray, T: int,
                               lookback: int = 60, min_gap: int = 5) -> bool:
        """检查 [T-lookback, T] 内是否存在 MACD 底背离。

        底背离定义（任一成立）：
        A) DIF 底背离：存在两个价格低点 L1(早) L2(晚)，close[L2] ≤ close[L1] 且 DIF[L2] > DIF[L1]
        B) MACD 柱底背离：存在两个绿柱谷底 G1(早) G2(晚)，close[G2] ≤ close[G1] 且 macd_bar[G2] > macd_bar[G1]
        """
        start = max(1, T - lookback)
        if T - start < min_gap * 2:
            return False

        # 找区间内的局部低点（close 维度）
        lows = []
        for i in range(start + 1, T):
            if closes[i] <= closes[i - 1] and closes[i] <= closes[i + 1]:
                lows.append(i)

        # A) DIF 底背离
        for i in range(len(lows)):
            for j in range(i + 1, len(lows)):
                l1, l2 = lows[i], lows[j]
                if l2 - l1 < min_gap:
                    continue
                if closes[l2] <= closes[l1] and dif[l2] > dif[l1]:
                    return True

        # B) MACD 柱底背离（绿柱谷底）
        green_valleys = []
        for i in range(start + 1, T):
            if macd_bar[i] < 0 and macd_bar[i] <= macd_bar[i - 1] and macd_bar[i] <= macd_bar[i + 1]:
                green_valleys.append(i)

        for i in range(len(green_valleys)):
            for j in range(i + 1, len(green_valleys)):
                g1, g2 = green_valleys[i], green_valleys[j]
                if g2 - g1 < min_gap:
                    continue
                if closes[g2] <= closes[g1] and macd_bar[g2] > macd_bar[g1]:
                    return True

        return False

    # ------------------------------------------------------------------
    # 量能放大事件
    # ------------------------------------------------------------------
    @staticmethod
    def _has_volume_surge(volumes: np.ndarray, T: int,
                         lookback: int = 30, ratio: float = 2.0,
                         base_window: int = 20) -> bool:
        """检查 [T-lookback, T] 内是否存在量能放大事件。"""
        start = max(base_window, T - lookback)
        for i in range(start, T + 1):
            base_start = max(0, i - base_window)
            base = volumes[base_start:i]
            valid = base[base > 0]
            if len(valid) < 5:
                continue
            avg = float(np.mean(valid))
            if avg > 0 and volumes[i] / avg >= ratio:
                return True
        return False

    @staticmethod
    def _find_vol_surge_day(volumes: np.ndarray, T: int,
                           lookback: int = 30, base_window: int = 20) -> int:
        """找到最近的量能放大日索引（按量比最大者）。"""
        start = max(base_window, T - lookback)
        best_idx = T
        best_ratio = 0.0
        for i in range(start, T + 1):
            base_start = max(0, i - base_window)
            base = volumes[base_start:i]
            valid = base[base > 0]
            if len(valid) < 5:
                continue
            avg = float(np.mean(valid))
            if avg > 0:
                r = volumes[i] / avg
                if r > best_ratio:
                    best_ratio = r
                    best_idx = i
        return best_idx

    # ------------------------------------------------------------------
    # 黄白线计算
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_white(closes: np.ndarray, T: int) -> float:
        """趋势白 = EMA(EMA(C,10),10)，返回 T 位置的值。"""
        n = T + 1
        if n < 20:
            return 0.0
        m = 2.0 / 11.0
        ema1 = np.zeros(n)
        ema1[0] = closes[0]
        for i in range(1, n):
            ema1[i] = ema1[i - 1] + m * (closes[i] - ema1[i - 1])
        ema2 = np.zeros(n)
        ema2[0] = ema1[0]
        for i in range(1, n):
            ema2[i] = ema2[i - 1] + m * (ema1[i] - ema2[i - 1])
        return float(ema2[T])

    @staticmethod
    def _calc_yellow(closes: np.ndarray, T: int) -> float:
        """大哥黄 = (MA14 + MA28 + MA57 + MA114) / 4，返回 T 位置的值。"""
        n = T + 1
        if n < 114:
            return 0.0
        total = 0.0
        for w in (14, 28, 57, 114):
            if n < w:
                return 0.0
            total += float(np.mean(closes[T - w + 1: T + 1]))
        return total / 4.0

    # ------------------------------------------------------------------
    # 翻番过滤
    # ------------------------------------------------------------------
    def _recently_doubled(self, closes: np.ndarray) -> bool:
        n = self.doubled_lookback
        if n <= 0 or len(closes) < n:
            return False
        win = closes[-n:]
        valid = win[win > 0]
        if len(valid) < 2:
            return False
        return float(np.max(valid)) / float(np.min(valid)) >= self.doubled_ratio

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def min_bars_required(divergence_lookback: int = 60) -> int:
        return divergence_lookback + 114  # 黄线需要 114 根

    @staticmethod
    def _is_kc_board(symbol: str) -> bool:
        return symbol.startswith("30") or symbol.startswith("68") or symbol.startswith("8")
