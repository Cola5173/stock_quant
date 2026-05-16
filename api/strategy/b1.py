"""
B1 策略
异动突破 + 回踩企稳 买入策略

买入条件（全部满足）：
1. 趋势白 > 大哥黄，收盘价在大哥黄之上（多头格局）
2. KDJ J < 15（超卖）
3. 前20日阳线占比 >= 50%（红肥绿瘦）
4. 异动突破：过去 N 日内存在某一天，放量阳线、单日涨幅3%~13%（斜率不高、建仓特征），
   且收盘从大哥黄下方"一举站上"大哥黄（前一日收盘<=大哥黄，当日收盘>大哥黄）
5. 异动后企稳：从异动日到当前 T-1，跌破大哥黄天数 <= 3，期间无放量大阴线

卖出条件（任一触发）：
1. 连续2天收盘低于大哥黄
2. 持仓>=5天且亏损超5%（止损）
3. 放量大阴线（量比>1.5 且 跌幅>5%）
4. 盈利>=15%后，从最高点回撤超1/3（动态回撤止盈）
5. J>90 且趋势白拐头向下 且盈利>5% 且最高盈利<15%（短线止盈）
6. 已脱离成本区（持仓最高盈利>=15%）后，连续2天收盘低于趋势白（主升阶段趋势结束）
"""
import numpy as np
import pandas as pd
from vnpy.trader.object import BarData
from api.strategy.base_strategy import BaseStrategy


class B1Strategy(BaseStrategy):
    """B1 策略：异动突破回踩企稳"""

    author = "stock_quant"

    kdj_j_threshold = 15
    red_ratio_min = 50

    burst_lookback_days = 30
    burst_min_chg = 3.0
    burst_max_chg = 13.0
    burst_vol_ratio = 1.3

    stable_below_yellow_max = 3
    stable_drop_pct = 5.0
    stable_drop_vol_ratio = 1.5

    stop_loss_days = 5
    stop_loss_pct = -5.0
    below_yellow_days_limit = 2
    below_white_days_limit = 2
    main_up_profit_threshold = 15.0
    sell_vol_ratio = 1.5
    sell_drop_pct = 5.0
    trailing_start_pct = 15.0
    trailing_drawdown_ratio = 0.33
    short_tp_j = 90
    short_tp_min_profit = 5.0

    parameters = [
        "kdj_j_threshold", "red_ratio_min",
        "burst_lookback_days", "burst_min_chg", "burst_max_chg", "burst_vol_ratio",
        "stable_below_yellow_max", "stable_drop_pct", "stable_drop_vol_ratio",
        "stop_loss_days", "stop_loss_pct",
        "below_yellow_days_limit", "below_white_days_limit", "main_up_profit_threshold",
        "sell_vol_ratio", "sell_drop_pct",
        "trailing_start_pct", "trailing_drawdown_ratio",
        "short_tp_j", "short_tp_min_profit",
    ]
    variables = ["hold_days", "buy_price", "max_profit_pct",
                 "below_yellow_count", "below_white_count"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.hold_days = 0
        self.buy_price = 0.0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0
        self.prev_trend_white = 0.0

    @staticmethod
    def _yellow_series(closes: np.ndarray) -> np.ndarray:
        s = pd.Series(closes)
        return ((s.rolling(14, min_periods=1).mean()
                 + s.rolling(28, min_periods=1).mean()
                 + s.rolling(57, min_periods=1).mean()
                 + s.rolling(114, min_periods=1).mean()) / 4.0).values

    @staticmethod
    def _prev_vol_ratio(volumes: np.ndarray, i: int, window: int = 5) -> float:
        if i < window:
            return 0.0
        base = float(np.mean(volumes[i - window:i]))
        return volumes[i] / base if base > 0 else 0.0

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        am = self.am
        closes = am.close_array
        opens = am.open_array
        volumes = am.volume_array

        zx = self.indicator.zx_trend()
        trend_white = zx["white"]
        big_bro_yellow = zx["yellow"]
        kdj = self.indicator.kdj()
        j_val = kdj["J"]

        if self.pos > 0:
            self.hold_days += 1
            if self.buy_price > 0:
                cur_profit = (bar.close_price - self.buy_price) / self.buy_price * 100
                self.max_profit_pct = max(self.max_profit_pct, cur_profit)

        # ========== 卖出逻辑 ==========
        if self.pos > 0 and can_sell and not at_lower_limit:
            if self.buy_price <= 0:
                return
            sell = False
            cur_profit = (bar.close_price - self.buy_price) / self.buy_price * 100

            if bar.close_price < big_bro_yellow:
                self.below_yellow_count += 1
            else:
                self.below_yellow_count = 0
            if self.below_yellow_count >= self.below_yellow_days_limit:
                sell = True

            if bar.close_price < trend_white:
                self.below_white_count += 1
            else:
                self.below_white_count = 0
            if (self.below_white_count >= self.below_white_days_limit
                    and self.max_profit_pct >= self.main_up_profit_threshold):
                sell = True

            if self.hold_days >= self.stop_loss_days and cur_profit < self.stop_loss_pct:
                sell = True

            vol_ma5 = float(np.mean(volumes[-6:-1]))
            cur_vol_ratio = bar.volume / vol_ma5 if vol_ma5 > 0 else 0
            cur_drop = (bar.open_price - bar.close_price) / bar.open_price * 100
            if cur_vol_ratio > self.sell_vol_ratio and cur_drop > self.sell_drop_pct:
                sell = True

            if self.max_profit_pct >= self.trailing_start_pct:
                drawdown = self.max_profit_pct - cur_profit
                if drawdown >= self.max_profit_pct * self.trailing_drawdown_ratio:
                    sell = True

            if (j_val > self.short_tp_j
                    and cur_profit > self.short_tp_min_profit
                    and self.max_profit_pct < self.trailing_start_pct
                    and trend_white < self.prev_trend_white):
                sell = True

            if sell:
                self.sell_stock(bar.close_price, abs(self.pos))
                self._reset_state()

            self.prev_trend_white = trend_white
            return

        self.prev_trend_white = trend_white

        # ========== 买入逻辑 ==========
        if self.pos > 0 or at_upper_limit:
            return

        # 条件1: 多头格局
        if trend_white <= big_bro_yellow or bar.close_price <= big_bro_yellow:
            return

        # 条件2: J < 阈值（超卖）
        if j_val >= self.kdj_j_threshold:
            return

        # 条件3: 前20日红肥绿瘦
        recent_closes = closes[-21:-1]
        recent_opens = opens[-21:-1]
        red_count = int(np.sum(recent_closes >= recent_opens))
        if red_count / 20 * 100 < self.red_ratio_min:
            return

        # 条件4: 异动突破（窗口内最早一次"放量阳线 + 突破大哥黄"）
        N = self.burst_lookback_days
        n_total = len(closes)
        if n_total < N + 6:
            return

        yellow_arr = self._yellow_series(closes)

        burst_idx = -1
        for i in range(max(5, n_total - N - 1), n_total - 1):
            o, c = opens[i], closes[i]
            if o <= 0 or c < o:
                continue
            chg = (c - o) / o * 100
            if chg < self.burst_min_chg or chg >= self.burst_max_chg:
                continue
            vol_r = self._prev_vol_ratio(volumes, i)
            if vol_r < self.burst_vol_ratio:
                continue
            if closes[i - 1] > yellow_arr[i - 1]:
                continue
            if c <= yellow_arr[i]:
                continue
            burst_idx = i
            break

        if burst_idx < 0:
            return

        # 条件5: 异动后企稳（无放量大阴线 + 跌破大哥黄天数受限）
        below_count = 0
        for i in range(burst_idx + 1, n_total - 1):
            if closes[i] < yellow_arr[i]:
                below_count += 1
            o, c = opens[i], closes[i]
            if o <= 0:
                continue
            drop_pct = (o - c) / o * 100
            vol_r = self._prev_vol_ratio(volumes, i)
            if drop_pct > self.stable_drop_pct and vol_r > self.stable_drop_vol_ratio:
                return

        if below_count > self.stable_below_yellow_max:
            return

        # 全部条件满足，买入
        self.buy_full(bar.close_price)
        self.buy_price = bar.close_price
        self.hold_days = 0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0

    def _reset_state(self):
        self.hold_days = 0
        self.buy_price = 0.0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0

    def on_trade(self, trade):
        super().on_trade(trade)
        if trade.direction.value == "多":
            self.buy_price = trade.price
            self.hold_days = 0
            self.max_profit_pct = 0.0
            self.below_yellow_count = 0
            self.below_white_count = 0
