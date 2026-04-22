"""
B1 策略
KDJ + 知行趋势选股策略，适配 vnpy CTA 回测框架
"""
from vnpy.trader.object import BarData
from strategy.base_strategy import BaseStrategy


class B1Strategy(BaseStrategy):
    """B1 策略：KDJ J 值低位 + 趋势白线在黄线上方"""

    author = "stock_quant"

    kdj_n = 9
    kdj_j_buy = 13
    kdj_j_sell = 80
    trade_volume = 100

    parameters = ["kdj_n", "kdj_j_buy", "kdj_j_sell", "trade_volume"]
    variables = []

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        kdj = self.indicator.kdj(n=self.kdj_n)
        zx = self.indicator.zx_trend()

        # 买入条件：J < 阈值 且 白线在黄线上方 且 收盘价在黄线 -1% 之上 且 未涨停
        if (self.pos == 0
                and not at_upper_limit
                and kdj["J"] < self.kdj_j_buy
                and zx["white"] > zx["yellow"]
                and bar.close_price > zx["yellow"] * 0.99):
            self.buy_stock(bar.close_price, self.trade_volume)

        # 卖出条件：J > 阈值 且 可以卖出（T+1）且 未跌停
        if (self.pos > 0
                and can_sell
                and not at_lower_limit
                and kdj["J"] > self.kdj_j_sell):
            self.sell_stock(bar.close_price, abs(self.pos))
