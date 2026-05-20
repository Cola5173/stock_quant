"""
B1 策略
异动突破 + 回踩企稳 买入策略（含放飞盈利分批减仓）

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
  扣分因子（建仓阶段不健康信号）：
    I 跳空: 向下≥1% -1, 向下≥3% -2, 向上≥3% -1（累计）
    J 量价背离: 阴线放量(跌≥1.5%且量比≥1.2) -1, 阴线巨量(跌≥2.5%且量比≥1.5) -2,
               阳线缩量(涨≥2%且量比≤0.4) -1, 高位阳线放巨量(涨≥2%且量比≥2.5) -1（累计）

卖出条件（三层优先级）：
  Layer 1 — 强制退出（全仓清出）：
    1. 收盘跌破止损价
    2. 放量大阴线（量比>1.5 且 跌幅>5%）
    3. 连续2天收盘低于大哥黄
  Layer 2 — 趋势退出（全仓清出，仅整笔盈利时触发破白）：
    4. 主升回撤1/3止盈（盈利>=15%后从峰值回撤超1/3）
    5. J高位+白拐头短线止盈
    6. 连续2天破白线（仅当整笔交易含已减仓部分盈利时触发）
  Layer 3 — 放飞减仓（部分卖出，不清仓）：
    7. 中大阳线（body > ATR * big_yang_atr_mult）时分批减仓
       第一次减 original_volume * 1/3，第二次减 remaining * 1/2

止损进化：
  - 初始止损：趋势白/大哥黄/买入日低点（按距离判断）
  - 第一次减仓后：止损提升到至少买入价（保本）
  - 第二次减仓后：止损提升到至少趋势白（趋势保护）
  - 原则：止损价只升不降
"""
import numpy as np
import pandas as pd
from vnpy.trader.object import BarData
from api.strategy.base_strategy import BaseStrategy


def _apply_b1_env_overrides(cls):
    """从环境变量覆盖 B1 类属性，便于 sweep 时通过 subprocess + env 传参。

    支持的环境变量（前缀 B1_，全大写）:
      B1_SCORE_THRESHOLD / B1_KEYK_ENABLED / B1_KEYK_BURST_WEIGHT / ...
    """
    import os
    overridable = [
        "score_threshold",
        "keyk_enabled", "keyk_premise_weight", "keyk_hold_weight",
        "keyk_today_weight", "keyk_score_threshold",
        "keyk_premise_lookback", "keyk_control_lookahead",
        "after_burst_dd_enabled",
        "after_burst_dd_t1", "after_burst_dd_t2", "after_burst_dd_t3",
        "ma60_uptrend_enabled", "ma60_slope_min",
    ]
    for name in overridable:
        env_key = f"B1_{name.upper()}"
        if env_key not in os.environ:
            continue
        raw = os.environ[env_key].strip()
        cur = getattr(cls, name)
        try:
            if isinstance(cur, bool):
                setattr(cls, name, raw.lower() in ("1", "true", "yes", "on"))
            elif isinstance(cur, float):
                setattr(cls, name, float(raw))
            else:
                setattr(cls, name, int(raw))
        except (ValueError, TypeError):
            pass


class B1Strategy(BaseStrategy):
    """B1 策略：异动突破回踩企稳"""

    author = "stock_quant"

    kdj_j_threshold = 15
    red_ratio_min = 50
    red_window_size = 21

    yellow_buy_buffer = 1.00

    burst_lookback_days = 50
    burst_min_chg = 2.5
    burst_max_chg = 13.0
    burst_vol_ratio = 1.3
    burst_recent_below_days = 5
    burst_max_above_yellow_pct = 5.0   # 异动日 open 距大哥黄最大偏离
    burst_pre_range_days = 20           # 异动前窄幅震荡检测窗口
    burst_pre_range_max_ratio = 1.12    # 异动前 max/min 上限

    stable_below_yellow_max = 5
    stable_drop_pct = 5.0              # 异动后放量大阴阈值（恢复原值）
    stable_drop_vol_ratio = 1.5
    burst_exhaustion_pct = 15.0        # 异动后涨幅超此值
    burst_exhaustion_pullback_pct = 5.0 # 且从峰值回落超此值 → 视为行情已走完

    macd_cross_lookback = 60
    divergence_price_max = 25.0
    divergence_min_gap_days = 5

    # 多因子打分阈值
    score_threshold = 5

    # L 异动后最大回撤扣分（"回得太多说明弱"，从 burst close 起算到当前 close 的最大回撤）
    # 默认关闭：1.5 年回测 5/10/15 档位 → +39%，8/12/18 → -20%，15+ → +108%（≈基线）
    # 结论：扣分干扰排序，把好票挤后；除非档位严到几乎不触发，否则都是退步
    after_burst_dd_enabled = False
    after_burst_dd_t1 = 5.0       # 回撤 ≥ 5% → -1
    after_burst_dd_t2 = 10.0      # 回撤 ≥ 10% → -2
    after_burst_dd_t3 = 15.0      # 回撤 ≥ 15% → -3

    # 关键 K 加分维度（patterns 形态库）
    # 设计：异动日之前的「建仓基础」+ 控制力延续 + 决策日二次启动
    # 默认关闭：1.5 年回测显示加分参与 ranking 会挤掉好票（年化 +109% → -8%），
    # 形态库代码保留供「反向过滤」「决策日二次确认」等场景后续接入
    keyk_enabled = False
    keyk_premise_weight = 2        # 异动日之前 N 日内出现过 entry 关键 K
    keyk_hold_weight = 1           # 异动日最低价 ≥ 关键 K 低点（建仓底部未失守）
    keyk_today_weight = 1          # 决策日是 entry 关键 K（二次启动）
    keyk_score_threshold = 60      # 关键 K score≥此视为成立
    keyk_premise_lookback = 60     # 异动日往前回看天数（找 entry 关键 K）
    keyk_control_lookahead = 5     # 控制力观察日数（保留以便扩展）

    # M MA60 拐头向上硬过滤（中期趋势扭转 — 不参与排序，仅决定入不入选）
    # 异动日的 MA60 必须有正斜率（向上），否则中期趋势未扭转，整票淘汰
    # 默认关闭：1.5 年回测 +109% → +67%，被过滤掉的 10 笔里有大赚票
    # 推断：B1 抓的是"建仓尾声"，那时 MA60 多半还没拐头；等转正才入场反而晚了
    ma60_uptrend_enabled = False
    ma60_period = 60
    ma60_slope_window = 5         # 比较 ma60[i] 与 ma60[i-window]
    ma60_slope_min = 0.0          # 至少要 > 0 才算拐头（可调高要求更陡）

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

    # 放飞减仓参数
    big_yang_atr_mult = 1.5  # 中大阳线阈值 = body_pct > ATR_pct * mult
    scale_out_1_ratio = 1.0 / 3.0  # 第一次减仓比例（占原始仓位）
    scale_out_2_ratio = 0.5  # 第二次减仓比例（占剩余仓位）

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
        "big_yang_atr_mult", "scale_out_1_ratio", "scale_out_2_ratio",
    ]
    variables = ["hold_days", "buy_price", "buy_day_low", "stop_loss_price",
                 "max_profit_pct", "below_yellow_count", "below_white_count",
                 "bars_since_last_sell",
                 "original_volume", "scale_stage", "realized_pnl"]

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
        self.bars_since_last_sell = 9999
        # 放飞减仓状态
        self.original_volume = 0  # 原始买入股数
        self.scale_stage = 0  # 减仓阶段（0=未减, 1=已减一次, 2=已减两次）
        self.realized_pnl = 0.0  # 已实现盈亏（部分卖出累计）

    @staticmethod
    def _ma60_uptrend(closes: np.ndarray, idx: int, period: int = 60,
                      slope_window: int = 5, slope_min: float = 0.0) -> bool:
        """异动日 idx 的 MA{period} 是否拐头向上（中期趋势扭转）。

        通过比较 MA[idx] 与 MA[idx-slope_window] 判断斜率方向。
        斜率严格 > slope_min 才算拐头。前置数据不足返回 False（保守）。
        """
        if idx < period + slope_window:
            return False
        s = pd.Series(closes[: idx + 1])
        ma = s.rolling(period, min_periods=period).mean().values
        cur = ma[idx]
        prev = ma[idx - slope_window]
        if np.isnan(cur) or np.isnan(prev) or prev <= 0:
            return False
        slope_pct = (cur - prev) / prev * 100
        return slope_pct > slope_min

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
            cur_profit = (bar.close_price - self.buy_price) / self.buy_price * 100

            # --- 更新 below_yellow / below_white 计数 ---
            if bar.close_price < big_bro_yellow:
                self.below_yellow_count += 1
            else:
                self.below_yellow_count = 0
            if bar.close_price < trend_white:
                self.below_white_count += 1
            else:
                self.below_white_count = 0

            # --- Layer 1: 强制退出（全仓清出） ---
            force_exit = ""

            if self.stop_loss_price > 0 and bar.close_price < self.stop_loss_price:
                force_exit = f"收盘跌破止损价{self.stop_loss_price:.2f}"

            if not force_exit:
                vol_ma5 = float(np.mean(volumes[-6:-1]))
                cur_vol_ratio = bar.volume / vol_ma5 if vol_ma5 > 0 else 0
                cur_drop = (bar.open_price - bar.close_price) / bar.open_price * 100
                if cur_vol_ratio > self.sell_vol_ratio and cur_drop > self.sell_drop_pct:
                    force_exit = f"放量大阴线(量比{cur_vol_ratio:.1f}/跌{cur_drop:.1f}%)"

            if not force_exit and self.below_yellow_count >= self.below_yellow_days_limit:
                force_exit = "连续2天破大哥黄"

            if force_exit:
                self.sell_stock(bar.close_price * 10, abs(self.pos), reason=force_exit)
                self.prev_trend_white = trend_white
                return

            # --- Layer 2: 趋势退出（全仓清出） ---
            trend_exit = ""

            # 回撤止盈和 J 高短线止盈仅在未减仓时触发（减仓后放飞，靠破白退出）
            if self.scale_stage == 0:
                if self.max_profit_pct >= self.trailing_start_pct:
                    drawdown = self.max_profit_pct - cur_profit
                    if drawdown >= self.max_profit_pct * self.trailing_drawdown_ratio:
                        trend_exit = f"主升回撤1/3止盈(峰值{self.max_profit_pct:.1f}%)"

                if not trend_exit and (j_val > self.short_tp_j
                        and cur_profit > self.short_tp_min_profit
                        and self.max_profit_pct < self.trailing_start_pct
                        and trend_white < self.prev_trend_white):
                    trend_exit = f"J高位+白拐头短线止盈(盈利{cur_profit:.1f}%)"

            # 破白清仓：仅当整笔交易（含已减仓部分）盈利时触发
            if not trend_exit and self.below_white_count >= self.below_white_days_limit:
                unrealized = (bar.close_price - self.buy_price) * abs(self.pos)
                overall_pnl = self.realized_pnl + unrealized
                if overall_pnl > 0:
                    trend_exit = "整笔盈利+连续2天破白清仓"

            if trend_exit:
                self.sell_stock(bar.close_price * 10, abs(self.pos), reason=trend_exit)
                self.prev_trend_white = trend_white
                return

            # --- Layer 3: 放飞减仓（部分卖出，不 reset） ---
            if self.scale_stage < 2:
                atr_val = self.indicator.atr(20)
                if self._is_big_yang(bar, atr_val):
                    if self.scale_stage == 0:
                        sell_vol = int(self.original_volume * self.scale_out_1_ratio // 100) * 100
                        reason = f"中大阳线减仓1/3(body>{self.big_yang_atr_mult:.1f}xATR)"
                    else:
                        remaining = abs(self.pos)
                        sell_vol = int(remaining * self.scale_out_2_ratio // 100) * 100
                        reason = f"中大阳线减仓1/2(body>{self.big_yang_atr_mult:.1f}xATR)"
                    if sell_vol >= 100 and sell_vol < abs(self.pos):
                        self.sell_stock(bar.close_price * 10, sell_vol, reason=reason)
                        self.scale_stage += 1
                        # 止损进化：只升不降
                        if self.scale_stage == 1:
                            self.stop_loss_price = max(self.stop_loss_price, self.buy_price)
                        elif self.scale_stage == 2:
                            self.stop_loss_price = max(self.stop_loss_price, trend_white)

            self.prev_trend_white = trend_white
            return

        self.prev_trend_white = trend_white

        # ========== 买入逻辑 ==========
        if self.pos > 0 or at_upper_limit:
            return

        # 条件1: 多头格局（收盘需高于大哥黄一定 buffer，避免买在支撑位边缘）
        if trend_white <= big_bro_yellow or bar.close_price < big_bro_yellow * self.yellow_buy_buffer:
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
        self.scale_stage = 0
        self.realized_pnl = 0.0

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
                       dif_arr, dea_arr, j_arr, n_total,
                       highs=None, lows=None, df=None, today_idx=None):
        """对指定 burst_idx 计算多因子打分，返回 (score, breakdown_list)

        df / today_idx 为可选；提供时启用关键 K 加分维度（不传则向后兼容跳过）。"""
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

        # I 跳空扣分（建仓阶段出现跳空 = 节奏不健康）
        if highs is None:
            highs = self.am.high_array
        if lows is None:
            lows = self.am.low_array
        i_score = 0
        for jj in range(burst_idx + 2, n_total - 1):
            if lows[jj - 1] > 0 and highs[jj] < lows[jj - 1]:
                gap_pct = (lows[jj - 1] - highs[jj]) / lows[jj - 1] * 100
                if gap_pct >= 3.0:
                    i_score -= 2
                elif gap_pct >= 1.0:
                    i_score -= 1
            elif highs[jj - 1] > 0 and lows[jj] > highs[jj - 1]:
                gap_pct = (lows[jj] - highs[jj - 1]) / highs[jj - 1] * 100
                if gap_pct >= 3.0:
                    i_score -= 1
        score += i_score
        breakdown.append(f"跳空:{i_score}")

        # J 量价背离扣分（建仓阶段量价关系异常，排除主升阳线）
        j_penalty = 0
        for jj in range(burst_idx + 1, n_total - 1):
            o, c = opens[jj], closes[jj]
            if o <= 0:
                continue
            vr = self._prev_vol_ratio(volumes, jj)
            chg = (c - o) / o * 100
            if chg >= 5.0:
                continue
            if chg < 0:
                drop = -chg
                if drop >= 2.5 and vr >= 1.5:
                    j_penalty -= 2
                elif drop >= 1.5 and vr >= 1.2:
                    j_penalty -= 1
            else:
                if chg >= 2.0 and vr <= 0.4:
                    j_penalty -= 1
                elif chg >= 2.0 and vr >= 2.5:
                    j_penalty -= 1
        score += j_penalty
        breakdown.append(f"量价:{j_penalty}")

        # L 异动后最大回撤扣分（"回得太多说明弱，给外盘便宜筹码"）
        if self.after_burst_dd_enabled:
            burst_close_val = float(closes[burst_idx])
            after_closes = closes[burst_idx + 1: n_total]
            if len(after_closes) > 0 and burst_close_val > 0:
                min_after = float(np.min(after_closes))
                dd_pct = (burst_close_val - min_after) / burst_close_val * 100
            else:
                dd_pct = 0.0
            l_score = 0
            if dd_pct >= self.after_burst_dd_t3:
                l_score = -3
            elif dd_pct >= self.after_burst_dd_t2:
                l_score = -2
            elif dd_pct >= self.after_burst_dd_t1:
                l_score = -1
            score += l_score
            breakdown.append(f"回撤{dd_pct:.0f}%:{l_score}")

        # K 关键 K 形态库加分（异动日"之前"找建仓基础 + 底部守护 + 决策日二次启动）
        if self.keyk_enabled and df is not None:
            from api.indicator.patterns import score_key_k
            # K1 异动日之前 keyk_premise_lookback 日内寻找 entry 关键 K
            premise_idx = -1
            premise_score = 0.0
            scan_start = max(1, burst_idx - self.keyk_premise_lookback)
            for i in range(scan_start, burst_idx):
                s = score_key_k(df, i)
                if s.direction == "entry" and s.score >= self.keyk_score_threshold and s.score > premise_score:
                    premise_idx = i
                    premise_score = s.score
            k1 = self.keyk_premise_weight if premise_idx >= 0 else 0
            score += k1
            breakdown.append(f"K前{int(premise_score)}:{k1}")

            # K2 异动日最低价 ≥ 关键 K 低点（建仓底部未失守）
            from api.schemas.kline_constants import KLineConstants as _KC
            if premise_idx >= 0:
                premise_low = float(df.iloc[premise_idx][_KC.LOW])
                burst_low = float(df.iloc[burst_idx][_KC.LOW])
                k2 = self.keyk_hold_weight if burst_low >= premise_low else 0
            else:
                k2 = 0
            score += k2
            breakdown.append(f"K守:{k2}")

            # K3 决策日是 entry 关键 K（二次启动）
            if today_idx is not None and today_idx > burst_idx:
                today_score = score_key_k(df, today_idx)
                k3 = self.keyk_today_weight if (
                    today_score.direction == "entry"
                    and today_score.score >= self.keyk_score_threshold
                ) else 0
                score += k3
                breakdown.append(f"K今{int(today_score.score)}:{k3}")
            else:
                breakdown.append("K今:0")

        return score, breakdown

    def _reset_state(self):
        self.hold_days = 0
        self.buy_price = 0.0
        self.buy_day_low = 0.0
        self.stop_loss_price = 0.0
        self.max_profit_pct = 0.0
        self.below_yellow_count = 0
        self.below_white_count = 0
        self.bars_since_last_sell = 0
        self.original_volume = 0
        self.scale_stage = 0
        self.realized_pnl = 0.0

    def _is_big_yang(self, bar: BarData, atr_val: float) -> bool:
        if bar.close_price <= bar.open_price or bar.open_price <= 0:
            return False
        body_pct = (bar.close_price - bar.open_price) / bar.open_price * 100
        atr_pct = atr_val / bar.open_price * 100 if bar.open_price > 0 else 0
        return atr_pct > 0 and body_pct > self.big_yang_atr_mult * atr_pct

    def on_trade(self, trade):
        super().on_trade(trade)
        if trade.direction.value == "多":
            self.buy_price = trade.price
            self.original_volume = int(trade.volume)
        else:
            if self.buy_price > 0:
                self.realized_pnl += (trade.price - self.buy_price) * trade.volume
            # 全仓卖出成交后才重置状态（避免 sell 单未成交时状态被错误清零）
            if self.pos == 0:
                self._reset_state()
            self.hold_days = 0
            self.max_profit_pct = 0.0
            self.below_yellow_count = 0
            self.below_white_count = 0


_apply_b1_env_overrides(B1Strategy)
