"""
主程序入口
"""
import argparse
from strategy.b1 import B1Strategy
from fetcher.baostock_fetcher import BaoStockDataFetcher


def main():
    start_date = '2025-01-01'
    end_date = '2025-12-05'

    print("--------------------------------")
    print(f"STEP 1: ----> 开始获取K线数据，日期范围：{start_date} 至 {end_date}")
    fetcher = BaoStockDataFetcher()
    fetcher.fetch(start_date, end_date)
    print(f"获取K线数据完成")

    print("--------------------------------")
    print(f"STEP2: ----> 开始执行选股策略...")
    b1_strategy = B1Strategy()
    # b1_strategy.select()
    print(f"选股策略执行完成")


if __name__ == '__main__':
    main()
