"""
Fetcher 数据下载测试
支持 tushare / akshare / baostock 三种数据源
用法：
    python fetcher/test_fetcher.py --source tushare --symbol 600000 --start 2025-01-01 --end 2025-05-15
    python fetcher/test_fetcher.py --source akshare --symbol 000001
    python fetcher/test_fetcher.py --source baostock --symbol 300750 --start 2025-03-01
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from datetime import datetime, timedelta


def main():
    parser = argparse.ArgumentParser(description="Fetcher 数据下载测试")
    parser.add_argument("--source", default="tushare",
                        choices=["tushare", "akshare", "baostock"],
                        help="数据源 (默认 tushare)")
    parser.add_argument("--symbol", default="600000", help="股票代码 (默认 600000)")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD (默认近30天)")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--list", action="store_true", help="测试获取全市场股票列表")
    args = parser.parse_args()

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    start_date = args.start or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    print(f"数据源: {args.source}")
    print(f"股票: {args.symbol}")
    print(f"区间: {start_date} ~ {end_date}")
    print("=" * 50)

    fetcher = _create_fetcher(args.source)

    # 测试1: 获取最近交易日
    print("\n[测试1] 获取最近交易日")
    last_trade_date = fetcher.get_last_trade_date()
    print(f"  最近交易日: {last_trade_date}")

    # 测试2: 获取全市场股票列表
    if args.list:
        print("\n[测试2] 获取全市场股票列表")
        stock_list = fetcher.get_all_stock_list(filter_st=True)
        print(f"  获取到 {len(stock_list)} 只股票")
        if stock_list:
            print(f"  前10只: {stock_list[:10]}")

    # 测试3: 下载单只股票数据
    print(f"\n[测试3] 下载 {args.symbol} K线数据")
    fetcher.fetch(start_date=start_date, end_date=end_date)

    # 验证下载结果
    csv_path = os.path.join("data", f"{args.symbol}.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        df = pd.read_csv(csv_path, parse_dates=["date"])
        print(f"\n[结果] {csv_path}")
        print(f"  总行数: {len(df)}")
        if not df.empty:
            print(f"  日期范围: {df['date'].min().strftime('%Y-%m-%d')} ~ {df['date'].max().strftime('%Y-%m-%d')}")
            print(f"  最新5条:")
            print(df.tail(5)[["date", "open", "high", "low", "close", "volume"]].to_string(index=False))
    else:
        print(f"\n[结果] 未找到 {csv_path}，下载可能失败")


def _create_fetcher(source: str):
    if source == "tushare":
        from fetcher.tushare_fetcher import TushareDataFetcher
        return TushareDataFetcher()
    elif source == "akshare":
        from fetcher.akshare_fetcher import AkShareDataFetcher
        return AkShareDataFetcher()
    else:
        from fetcher.baostock_fetcher import BaoStockDataFetcher
        return BaoStockDataFetcher()


if __name__ == "__main__":
    main()
