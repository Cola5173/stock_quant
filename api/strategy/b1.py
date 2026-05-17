"""
B1 策略
异动突破 + 回踩企稳 买入策略

买入条件（全部满足）：
1. 趋势白 > 大哥黄，收盘价在大哥黄之上（多头格局）
2. KDJ J < 15（超卖）
3. 异动日开始往后 N 天，红 K 累计涨幅 / (红涨+绿跌) >= 50%（红肥绿瘦：涨多于跌）
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
    red_window_size = 21

    burst_lookback_days = 50
    burst_min_chg = 2.5
    burst_max_chg = 13.0
    burst_vol_ratio = 1.3

    stable_below_yellow_max = 5
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
        "kdj_j_threshold", "red_ratio_min", "red_window_size",
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
            sell_reason = ""
            cur_profit = (bar.close_price - self.buy_price) / self.buy_price * 100

            if bar.close_price < big_bro_yellow:
                self.below_yellow_count += 1
            else:
                self.below_yellow_count = 0
            if self.below_yellow_count >= self.below_yellow_days_limit:
                sell_reason = sell_reason or "连续2天破大哥黄"

            if bar.close_price < trend_white:
                self.below_white_count += 1
            else:
                self.below_white_count = 0
            if (self.below_white_count >= self.below_white_days_limit
                    and self.max_profit_pct >= self.main_up_profit_threshold):
                sell_reason = sell_reason or "主升脱离成本破白清仓"

            if self.hold_days >= self.stop_loss_days and cur_profit < self.stop_loss_pct:
                sell_reason = sell_reason or f"持仓{self.hold_days}天亏损{cur_profit:.1f}%止损"

            vol_ma5 = float(np.mean(volumes[-6:-1]))
            cur_vol_ratio = bar.volume / vol_ma5 if vol_ma5 > 0 else 0
            cur_drop = (bar.open_price - bar.close_price) / bar.open_price * 100
            if cur_vol_ratio > self.sell_vol_ratio and cur_drop > self.sell_drop_pct:
                sell_reason = sell_reason or f"放量大阴线(量比{cur_vol_ratio:.1f}/跌{cur_drop:.1f}%)"

            if self.max_profit_pct >= self.trailing_start_pct:
                drawdown = self.max_profit_pct - cur_profit
                if drawdown >= self.max_profit_pct * self.trailing_drawdown_ratio:
                    sell_reason = sell_reason or f"主升回撤1/3止盈(峰值{self.max_profit_pct:.1f}%)"

            if (j_val > self.short_tp_j
                    and cur_profit > self.short_tp_min_profit
                    and self.max_profit_pct < self.trailing_start_pct
                    and trend_white < self.prev_trend_white):
                sell_reason = sell_reason or f"J高位+白拐头短线止盈(盈利{cur_profit:.1f}%)"

            if sell_reason:
                self.sell_stock(bar.close_price, abs(self.pos), reason=sell_reason)
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

        # 条件4: 异动突破（收集所有合规候选，c5 验证后取第一个通过的）
        N = self.burst_lookback_days
        n_total = len(closes)
        if n_total < N + 6:
            return

        yellow_arr = self._yellow_series(closes)

        candidates = []
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
            candidates.append(i)

        if not candidates:
            return

        # 条件5: 异动后企稳（无放量大阴线 + 跌破大哥黄天数受限）
        # 从最早异动日往后试，找第一个能通过企稳验证的
        burst_idx = -1
        for ci in candidates:
            below_count = 0
            big_drop = False
            for j in range(ci + 1, n_total - 1):
                if closes[j] < yellow_arr[j]:
                    below_count += 1
                o, c = opens[j], closes[j]
                if o <= 0:
                    continue
                drop_pct = (o - c) / o * 100
                vol_r = self._prev_vol_ratio(volumes, j)
                if drop_pct > self.stable_drop_pct and vol_r > self.stable_drop_vol_ratio:
                    big_drop = True
                    break
            if big_drop:
                continue
            if below_count > self.stable_below_yellow_max:
                continue
            burst_idx = ci
            break

        if burst_idx < 0:
            return

        # 条件3: 异动日开始往后 N 天的红肥绿瘦
        # 用累计幅度而非天数：红涨累计 / (红涨累计 + 绿跌累计) >= 50%
        win_start = burst_idx
        win_end = min(n_total - 1, burst_idx + self.red_window_size)
        win_closes = closes[win_start:win_end]
        win_opens = opens[win_start:win_end]
        win_len = len(win_closes)
        if win_len < 5:
            return
        chg_pct = np.where(win_opens > 0, (win_closes - win_opens) / win_opens * 100, 0.0)
        red_amp = float(np.sum(chg_pct[chg_pct > 0]))
        green_amp = float(-np.sum(chg_pct[chg_pct < 0]))
        total_amp = red_amp + green_amp
        if total_amp <= 0:
            return
        if red_amp / total_amp * 100 < self.red_ratio_min:
            return

        # 全部条件满足，买入
        self.buy_full(bar.close_price, reason="异动突破回踩企稳")
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
