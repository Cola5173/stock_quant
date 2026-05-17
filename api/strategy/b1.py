"""
B1 策略
异动突破 + 回踩企稳 买入策略

买入条件:
  基本条件（必须全部满足）：
    1. 多头格局：趋势白 > 大哥黄，收盘 > 大哥黄
    2. KDJ J < 15（超卖）
    3. 翻番过滤：最近 doubled_lookback 日内最高/最低 < doubled_ratio（已大幅上涨的不再买）
    4. 异动突破：过去 N 日存在放量阳，前 5 天有过收<=黄，当日收>黄，涨幅2.5-13%，量比≥1.3
    5. 异动后无放量大阴线（绝对底线）
  多因子打分（总分 ≥ score_threshold）：
    A 红肥绿瘦比例: ≥50% +1, ≥60% +2, ≥70% +3
    B 水下金叉（DIF<0 上穿 DEA）: +1
    C MACD 底背离（② MACD ≥ ①）: +2
    D J 底背离（② J > ①）: +1
    E 异动量比强度: ≥2 +1, ≥3 +2
    F 异动后地量企稳（后期均量比≤0.7）: +1
    G 跌破黄线快速收回（≤2 天回）: +1
    H 破黄总天数 ≤3: +1

卖出条件（任一触发）：
1. 连续2天收盘低于大哥黄
2. 跌破动态止损价（买入时计算 + 日内 low 触及即触发，成交价取 min(开盘价, 止损价)）：
   - 买入价在趋势白上方且距离>3%：止损=买入当天最低价
   - 买入价在趋势白上方且距离≤3%：止损=趋势白
   - 买入价在趋势白下方且距离大哥黄>3%：止损=买入当天最低价
   - 买入价在趋势白下方且距离大哥黄≤3%：止损=大哥黄
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
    burst_recent_below_days = 5

    stable_below_yellow_max = 5
    stable_drop_pct = 5.0
    stable_drop_vol_ratio = 1.5

    macd_cross_lookback = 60
    divergence_price_max = 25.0
    divergence_min_gap_days = 5

    # 多因子打分阈值
    score_threshold = 5

    # 翻番过滤：最近 doubled_lookback 日 max/min 比例 >= doubled_ratio 视为已大涨，跳过
    doubled_lookback = 60
    doubled_ratio = 1.8

    stop_loss_distance_pct = 3.0
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
        "burst_recent_below_days",
        "stable_below_yellow_max", "stable_drop_pct", "stable_drop_vol_ratio",
        "macd_cross_lookback", "divergence_price_max", "divergence_min_gap_days",
        "score_threshold",
        "doubled_lookback", "doubled_ratio",
        "stop_loss_distance_pct",
        "below_yellow_days_limit", "below_white_days_limit", "main_up_profit_threshold",
        "sell_vol_ratio", "sell_drop_pct",
        "trailing_start_pct", "trailing_drawdown_ratio",
        "short_tp_j", "short_tp_min_profit",
    ]
    variables = ["hold_days", "buy_price", "buy_day_low", "stop_loss_price",
                 "max_profit_pct", "below_yellow_count", "below_white_count",
                 "bars_since_last_sell"]

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.hold_days = 0
        self.buy_price = 0.0
        self.buy_day_low = 0.0
        self.stop_loss_price = 0.0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0
        self.prev_trend_white = 0.0
        # 9999 表示从未卖出过；卖出后重置为 0，每根 bar +1
        self.bars_since_last_sell = 9999

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

    @staticmethod
    def _macd_series(closes: np.ndarray) -> tuple:
        s = pd.Series(closes)
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        dif = (ema12 - ema26).values
        dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
        return dif, dea

    @staticmethod
    def _j_series(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray) -> np.ndarray:
        n = 9
        sc = pd.Series(closes)
        sh = pd.Series(highs)
        sl = pd.Series(lows)
        hh = sh.rolling(n, min_periods=1).max()
        ll = sl.rolling(n, min_periods=1).min()
        denom = (hh - ll).replace(0, np.nan)
        rsv = ((sc - ll) / denom * 100).fillna(50).replace([np.inf, -np.inf], 50).values
        k = np.full(len(rsv), 50.0)
        d = np.full(len(rsv), 50.0)
        for i in range(1, len(rsv)):
            k[i] = 2.0 / 3.0 * k[i-1] + 1.0 / 3.0 * rsv[i]
            d[i] = 2.0 / 3.0 * d[i-1] + 1.0 / 3.0 * k[i]
        return 3 * k - 2 * d

    def _recently_doubled(self, closes: np.ndarray) -> bool:
        """回看 doubled_lookback 日，max/min 比例 >= doubled_ratio 则视为已翻番。"""
        n = self.doubled_lookback
        if n <= 0 or len(closes) < n:
            return False
        window = closes[-n:]
        win_low = float(np.min(window))
        if win_low <= 0:
            return False
        win_high = float(np.max(window))
        return win_high / win_low >= self.doubled_ratio

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        am = self.am
        closes = am.close_array
        opens = am.open_array
        volumes = am.volume_array

        # 卖出冷却计数：每根 bar +1，卖出时在 _reset_state 中归零
        if self.bars_since_last_sell < 10**9:
            self.bars_since_last_sell += 1

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
            stop_triggered = False  # 标记是否仅由"日内触及止损"触发，决定成交价
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

            # 日内触及止损价立即触发（盘中实盘 stop loss 行为，不等收盘）
            if self.stop_loss_price > 0 and bar.low_price <= self.stop_loss_price:
                if not sell_reason:
                    sell_reason = f"日内跌破止损价{self.stop_loss_price:.2f}"
                    stop_triggered = True

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
                # 止损触发：跳空低开按开盘价，否则按止损价；其他原因按收盘价
                if stop_triggered:
                    sell_price = min(bar.open_price, self.stop_loss_price)
                else:
                    sell_price = bar.close_price
                self.sell_stock(sell_price, abs(self.pos), reason=sell_reason)
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

        # 条件3: 翻番过滤（最近 doubled_lookback 日 max/min 已超阈值的不再买）
        if self._recently_doubled(closes):
            return

        # 条件4: 异动突破（收集所有合规候选）
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
            look_back = max(1, self.burst_recent_below_days)
            recent_below = False
            for k in range(max(0, i - look_back), i):
                if closes[k] <= yellow_arr[k]:
                    recent_below = True
                    break
            if not recent_below:
                continue
            if c <= yellow_arr[i]:
                continue
            candidates.append(i)

        if not candidates:
            return

        # 条件5: 异动后无放量大阴线（基本底线）+ 打分 ≥ 阈值
        # 遍历候选异动日，找第一个"无放量大阴 + 打分通过"的
        highs = self.am.high_array
        lows = self.am.low_array
        dif_arr, dea_arr = self._macd_series(closes)
        j_arr = self._j_series(highs, lows, closes)

        burst_idx = -1
        score = 0
        breakdown = []
        for ci in candidates:
            big_drop = False
            for jj in range(ci + 1, n_total - 1):
                o, c = opens[jj], closes[jj]
                if o <= 0:
                    continue
                drop_pct = (o - c) / o * 100
                vol_r = self._prev_vol_ratio(volumes, jj)
                if drop_pct > self.stable_drop_pct and vol_r > self.stable_drop_vol_ratio:
                    big_drop = True
                    break
            if big_drop:
                continue
            cs, cb = self._compute_score(
                ci, closes, opens, volumes, yellow_arr,
                dif_arr, dea_arr, j_arr, n_total,
            )
            if cs >= self.score_threshold:
                burst_idx = ci
                score = cs
                breakdown = cb
                break

        if burst_idx < 0:
            return

        # 全部条件满足，买入
        reason = f"B1异动突破[分{score}|" + " ".join(breakdown) + "]"
        self.buy_full(bar.close_price, reason=reason)
        self.buy_price = bar.close_price
        self.buy_day_low = bar.low_price
        self.hold_days = 0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0

        # 计算止损价
        dist_pct = self.stop_loss_distance_pct / 100.0
        if bar.close_price >= trend_white:
            gap = (bar.close_price - trend_white) / bar.close_price
            if gap > dist_pct:
                self.stop_loss_price = bar.low_price
            else:
                self.stop_loss_price = trend_white
        else:
            gap = (bar.close_price - big_bro_yellow) / bar.close_price
            if abs(gap) > dist_pct:
                self.stop_loss_price = bar.low_price
            else:
                self.stop_loss_price = big_bro_yellow

    def _compute_score(self, burst_idx, closes, opens, volumes, yellow_arr,
                       dif_arr, dea_arr, j_arr, n_total):
        """对指定 burst_idx 计算 8 因子打分，返回 (score, breakdown_list)"""
        score = 0
        breakdown = []

        # A 红肥绿瘦
        win_start = burst_idx
        win_end = min(n_total - 1, burst_idx + self.red_window_size)
        win_closes = closes[win_start:win_end]
        win_opens = opens[win_start:win_end]
        red_score = 0
        red_pct = 0.0
        if len(win_closes) >= 5:
            chg_pct = np.where(win_opens > 0, (win_closes - win_opens) / win_opens * 100, 0.0)
            red_amp = float(np.sum(chg_pct[chg_pct > 0]))
            green_amp = float(-np.sum(chg_pct[chg_pct < 0]))
            total_amp = red_amp + green_amp
            if total_amp > 0:
                red_pct = red_amp / total_amp * 100
                if red_pct >= 70: red_score = 3
                elif red_pct >= 60: red_score = 2
                elif red_pct >= 50: red_score = 1
        score += red_score
        breakdown.append(f"红肥{red_pct:.0f}%:{red_score}")

        # B 水下金叉
        cross_start = max(1, burst_idx - self.macd_cross_lookback)
        has_cross = False
        for i in range(cross_start, burst_idx + 1):
            if (dif_arr[i - 1] <= dea_arr[i - 1]
                    and dif_arr[i] > dea_arr[i]
                    and dif_arr[i] < 0):
                has_cross = True
                break
        b_score = 1 if has_cross else 0
        score += b_score
        breakdown.append(f"金叉:{b_score}")

        # C/D 底背离
        j_lows = []
        scan_start = max(2, burst_idx - 150)
        for i in range(scan_start, burst_idx):
            if j_arr[i] < 0 and j_arr[i] < j_arr[i - 1] and j_arr[i] < j_arr[i + 1]:
                macd_val = (dif_arr[i] - dea_arr[i]) * 2.0
                j_lows.append((i, closes[i], macd_val, j_arr[i]))
        c_score = 0
        d_score = 0
        if len(j_lows) >= 2:
            idx2, p2_price, p2_macd, p2_j = j_lows[-1]
            gap = max(1, self.divergence_min_gap_days)
            prior = [pt for pt in j_lows[:-1] if idx2 - pt[0] >= gap]
            if prior:
                p1 = min(prior, key=lambda x: x[3])
                if p1[1] > 0:
                    price_diff = abs(p2_price - p1[1]) / p1[1] * 100
                    if price_diff <= self.divergence_price_max:
                        if p2_macd >= p1[2]: c_score = 2
                        if p2_j > p1[3]: d_score = 1
        score += c_score + d_score
        breakdown.append(f"MACD背:{c_score} J背:{d_score}")

        # E 异动量比强度
        burst_vr = self._prev_vol_ratio(volumes, burst_idx)
        if burst_vr >= 3.0: e_score = 2
        elif burst_vr >= 2.0: e_score = 1
        else: e_score = 0
        score += e_score
        breakdown.append(f"量比{burst_vr:.1f}:{e_score}")

        # F 异动后地量
        after_vols = volumes[burst_idx + 1:n_total - 1]
        f_score = 0
        avg_vr = 0.0
        if len(after_vols) >= 3:
            base_vol = float(np.mean(volumes[max(0, burst_idx - 20):burst_idx]))
            if base_vol > 0:
                avg_vr = float(np.mean(after_vols)) / base_vol
                if 0 < avg_vr <= 0.7: f_score = 1
        score += f_score
        breakdown.append(f"地量{avg_vr:.1f}:{f_score}")

        # G 跌破黄线快速收回
        g_score = 0
        below_streak = 0
        for jj in range(burst_idx + 1, n_total - 1):
            if closes[jj] < yellow_arr[jj]:
                below_streak += 1
            else:
                if 0 < below_streak <= 2:
                    g_score = 1
                below_streak = 0
        score += g_score
        breakdown.append(f"快收回:{g_score}")

        # H 破黄总天数 ≤3
        below_total = sum(1 for jj in range(burst_idx + 1, n_total - 1)
                          if closes[jj] < yellow_arr[jj])
        h_score = 1 if below_total <= 3 else 0
        score += h_score
        breakdown.append(f"破黄{below_total}:{h_score}")

        return score, breakdown

    def _reset_state(self):
        self.hold_days = 0
        self.buy_price = 0.0
        self.buy_day_low = 0.0
        self.stop_loss_price = 0.0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0
        # 卖出后重置冷却计数：异动日索引必须在本次卖出之后才允许再买
        self.bars_since_last_sell = 0

    def on_trade(self, trade):
        super().on_trade(trade)
        if trade.direction.value == "多":
            self.buy_price = trade.price
            self.hold_days = 0
            self.max_profit_pct = 0.0
            self.below_yellow_count = 0
            self.below_white_count = 0
