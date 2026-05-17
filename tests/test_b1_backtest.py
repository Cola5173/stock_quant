"""B1 策略回测：7 只标的近 2 年交易"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from api.schemas.models import BacktestRequest
from api.services.backtest_service import run_backtest

STOCKS = [
    ("600601", "方正科技"),
    ("688799", "华纳药厂"),
    ("601778", "晶科科技"),
    ("002929", "润建股份"),
    ("605168", "三人行"),
    ("002685", "华东重机"),
    ("600366", "宁波韵升"),
]

START = date(2024, 5, 17)
END = date(2026, 5, 17)
CAPITAL = 100000


def run_all():
    print(f"B1 策略回测 | 区间 {START} ~ {END} | 初始资金 {CAPITAL:,.0f}")
    print("=" * 90)

    for code, name in STOCKS:
        req = BacktestRequest(strategy="b1", code=code, start=START, end=END, capital=CAPITAL)
        try:
            resp = run_backtest(req)
        except Exception as e:
            print(f"\n{name}({code}): 回测失败 - {e}")
            continue

        stats = resp.stats
        print(f"\n{name}({code}) | 交易 {stats.total_trade_count} 笔 | "
              f"收益 {stats.total_return:.2f}% | 最大回撤 {stats.max_drawdown:.2f}% | "
              f"夏普 {stats.sharpe_ratio:.2f}")
        print("-" * 90)
        for t in resp.trades:
            print(f"  {t.date}  {t.direction:4s}  {t.price:8.2f} x{t.volume:<6d} | {t.reason[:60]}")

    print("\n" + "=" * 90)
    print("回测完成")


if __name__ == "__main__":
    run_all()
