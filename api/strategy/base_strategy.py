"""
策略基类
所有交易策略继承此类，实现 execute_logic 方法
"""
import json
import os

from vnpy_ctastrategy import CtaTemplate, StopOrder, BarGenerator, ArrayManager
from vnpy.trader.object import BarData, TickData, TradeData, OrderData
from vnpy.trader.constant import Interval

from api.indicator.indicators import IndicatorCalculator
from api.config import settings


class BaseStrategy(CtaTemplate):
    """vnpy CTA 策略基类，内置指标桥接和 A 股交易规则"""

    author = "stock_quant"

    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=200)
        self.indicator = None
        self.buy_date = None
        self.prev_close = 0.0
        self.cash = 0.0
        self.trade_reasons: list = []
        self._pending_buy_reason: str = ""
        self._pending_sell_reason: str = ""
        # 跟踪未撮合订单，避免重复下单时 limit 单堆积（vnpy CtaTemplate 不内置）
        self._active_buy_orderids: list = []
        self._active_sell_orderids: list = []
        self._extra_info = self._load_extra_info()

    def _load_extra_info(self) -> dict:
        path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {}

    def _get_limit_rate(self) -> float:
        symbol = self.vt_symbol.split(".")[0]
        info = self._extra_info.get(symbol, {})
        if info.get("is_st", False):
            return 0.05
        if symbol.startswith("30") or symbol.startswith("68"):
            return 0.20
        return 0.10

    def on_init(self):
        self.write_log("Strategy initialized")
        self.cash = float(getattr(self.cta_engine, "capital", 100000) or 100000)
        # 必须显式传 Interval.DAILY，否则 CtaTemplate.load_bar 默认 MINUTE 会导致数据库查空
        # ArrayManager(size=200) 需 200 交易日才 inited，350 自然日 ≈ 226 交易日，留余量保证 am 一上来就 inited
        self.load_bar(350, interval=Interval.DAILY)

    def on_start(self):
        self.write_log("Strategy started")

    def on_stop(self):
        self.write_log("Strategy stopped")

    def on_bar(self, bar: BarData):
        self.am.update_bar(bar)
        if not self.am.inited:
            self.prev_close = bar.close_price
            return

        self.indicator = IndicatorCalculator(self.am)

        # 涨跌停判断
        limit = self._get_limit_rate()
        pct = (bar.close_price - self.prev_close) / self.prev_close if self.prev_close > 0 else 0
        at_upper_limit = pct >= limit - 0.001
        at_lower_limit = pct <= -limit + 0.001

        # T+1：当日买入不可卖出
        can_sell = self.buy_date is not None and bar.datetime.date() > self.buy_date

        self.execute_logic(bar, can_sell, at_upper_limit, at_lower_limit)
        self.prev_close = bar.close_price

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        raise NotImplementedError

    def buy_stock(self, price: float, volume: float):
        """A 股买入：最小 100 股"""
        volume = int(volume // 100) * 100
        if volume > 0:
            self.buy(price, volume)

    def buy_full(self, price: float, reason: str = ""):
        """A 股满仓买入：用全部可用资金（扣留佣金后）按 100 股取整买入。
        使用 stop order 保证 next bar 按 max(price, open) 成交，避免跳空高开时 limit 单不撮合。"""
        if price <= 0 or self.cash <= 0:
            return
        for oid in list(self._active_buy_orderids):
            self.cancel_order(oid)
        rate = float(getattr(self.cta_engine, "rate", 0) or 0)
        affordable = self.cash / (price * (1 + rate))
        volume = int(affordable // 100) * 100
        if volume > 0:
            self._pending_buy_reason = reason
            vt_orderids = self.buy(price, volume, stop=True)
            if vt_orderids:
                self._active_buy_orderids.extend(vt_orderids)

    def sell_stock(self, price: float, volume: float, reason: str = ""):
        """A 股卖出。使用 stop order 保证 next bar 按 min(price, open) 成交。"""
        volume = int(volume // 100) * 100
        if volume <= 0:
            return
        for oid in list(self._active_sell_orderids):
            self.cancel_order(oid)
        self._pending_sell_reason = reason
        vt_orderids = self.sell(price, volume, stop=True)
        if vt_orderids:
            self._active_sell_orderids.extend(vt_orderids)

    def on_trade(self, trade: TradeData):
        rate = float(getattr(self.cta_engine, "rate", 0) or 0)
        amount = float(trade.price) * float(trade.volume)
        commission = amount * rate
        is_buy = trade.direction.value == "多"
        if is_buy:
            self.cash -= amount + commission
            self.buy_date = trade.datetime.date()
            reason = self._pending_buy_reason
            self._pending_buy_reason = ""
        else:
            self.cash += amount - commission
            reason = self._pending_sell_reason
            self._pending_sell_reason = ""
        self.trade_reasons.append({
            "date": trade.datetime.strftime("%Y-%m-%d"),
            "direction": "buy" if is_buy else "sell",
            "reason": reason,
        })

    def on_order(self, order: OrderData):
        # 订单结束（成交/撤销/拒绝）时从 active 列表移除，便于下次 buy_full/sell_stock 准确判断
        if not order.is_active():
            if order.vt_orderid in self._active_buy_orderids:
                self._active_buy_orderids.remove(order.vt_orderid)
            if order.vt_orderid in self._active_sell_orderids:
                self._active_sell_orderids.remove(order.vt_orderid)

    def on_stop_order(self, stop_order: StopOrder):
        pass
