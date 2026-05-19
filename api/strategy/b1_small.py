"""
B1 Small 策略
B1 策略的小资金变种（20w 专用）

核心改动（相对 B1Strategy）：
1. 选股范围：仅交易主板股票（600/000/001 开头）
   - 排除创业板（30 开头）、科创板（68 开头）、北交所（8 开头）
   - 新手账户限制：开户初期只能交易主板
2. 价格过滤：单价 ≤ 100 元
   - 小资金避免买不起或股数太少导致交易不灵活
3. 止损更严：弱市 -3%，强市 -5%
   - 小资金承受不起大回撤，快速止血保护本金
4. 时间止损更短：T+5 不涨即卖（B1 默认无时间止损）
   - 避免资金长期占用在弱势股
5. 个股冷却：止损后 20 日内不再买入同一只股票
   - 由组合层（PortfolioEngine）实现，策略层只负责单股逻辑

不变（继承 B1Strategy 的核心买入逻辑）：
- 多头格局 + KDJ 超卖 + 翻番过滤
- 异动突破 + 多因子打分（红肥绿瘦/水下金叉/底背离/量比/地量等）
- 放飞分批减仓（中大阳线减仓 1/3，再减 1/2）

使用：
    在 main.py strategy_map 中注册：
        "b1_small": B1SmallStrategy

    单股回测：
        python main.py backtest --strategy b1_small --symbol 600000 --start 2024-01-01 --end 2025-06-30

    组合回测（小资金 20w）：
        python main.py portfolio --strategy b1_small --capital 200000 --start 2024-01-01 --end 2025-06-30
"""
from vnpy.trader.object import BarData

from api.strategy.b1 import B1Strategy


class B1SmallStrategy(B1Strategy):
    """B1 小资金策略：仅主板 + 严格止损 + 时间止损"""

    author = "stock_quant"

    # === 小资金专属参数 ===
    max_price = 100.0
    time_stop_days = 5
    time_stop_min_gain_pct = 2.5  # 优化后：从 2.0 提到 2.5（参数扫描验证最优）
    weak_stop_loss_pct = 3.0
    strong_stop_loss_pct = 5.0

    # === 覆盖父类参数（更严格）===
    below_yellow_days_limit = 1

    parameters = B1Strategy.parameters + [
        "max_price",
        "time_stop_days",
        "time_stop_min_gain_pct",
        "weak_stop_loss_pct",
        "strong_stop_loss_pct",
    ]

    @staticmethod
    def is_main_board(symbol: str) -> bool:
        """主板判定：600/000/001 开头"""
        return (symbol.startswith("600")
                or symbol.startswith("000")
                or symbol.startswith("001"))

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        # === 入场前过滤（仅主板 + 价格 ≤ 50）===
        if self.pos == 0:
            symbol = self.vt_symbol.split(".")[0]
            if not self.is_main_board(symbol):
                return
            if bar.close_price > self.max_price:
                return

        # === 持仓中的额外卖出规则（在父类逻辑前先检查）===
        if self.pos > 0 and can_sell and not at_lower_limit and self.buy_price > 0:
            cur_profit = (bar.close_price - self.buy_price) / self.buy_price * 100

            # 1. 严格硬止损：弱市 -3%，强市 -5%
            #    判定：当日收盘是否在大哥黄之上视为强市
            zx = self.indicator.zx_trend()
            big_bro_yellow = zx["yellow"]
            market_strong = bar.close_price >= big_bro_yellow
            stop_pct = -self.strong_stop_loss_pct if market_strong else -self.weak_stop_loss_pct

            if cur_profit <= stop_pct:
                reason = f"小资金硬止损({stop_pct:.0f}%, 当前{cur_profit:+.2f}%)"
                self.sell_stock(bar.close_price * 10, abs(self.pos), reason=reason)
                return

            # 2. T+N 不涨即卖（仅在未减仓时触发）
            if (self.scale_stage == 0
                    and self.hold_days >= self.time_stop_days
                    and cur_profit < self.time_stop_min_gain_pct):
                reason = (f"T+{self.time_stop_days} 涨幅<{self.time_stop_min_gain_pct}%"
                          f"(当前{cur_profit:+.2f}%)")
                self.sell_stock(bar.close_price * 10, abs(self.pos), reason=reason)
                return

        # === 调用父类完整逻辑（异动突破买入 + 三层卖出 + 放飞减仓）===
        super().execute_logic(bar, can_sell, at_upper_limit, at_lower_limit)
