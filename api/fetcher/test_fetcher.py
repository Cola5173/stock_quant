"""
Fetcher 数据下载测试
支持 tushare / akshare / baostock 三种数据源
用法：
    python api/fetcher/test_fetcher.py --source tushare --symbol 600000 --start 2025-01-01 --end 2025-05-15
    python api/fetcher/test_fetcher.py --source tushare --start 2026-01-01  (不传 --symbol 则拉取全量)
    python api/fetcher/test_fetcher.py --source tushare --include-index    (全量 + 4 个板块基准指数)
    python api/fetcher/test_fetcher.py --source tushare --retry            (基于最新失败 JSON 续传)
    python api/fetcher/test_fetcher.py --source akshare --symbol 000001
    python api/fetcher/test_fetcher.py --list  (仅获取全市场股票列表)
"""
import sys
import os
import logging
# 项目根（test_fetcher.py 在 api/fetcher/，向上两级）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 默认显示 WARNING 及以上日志，便于看到网络重试错误
logging.basicConfig(level=logging.WARNING, format="%(levelname)s [%(name)s] %(message)s")

import argparse
import glob
import json
from datetime import datetime, timedelta

# 板块基准指数（与 portfolio_b1_top2 INDEX_MAP 保持一致）
DEFAULT_INDICES = [
    "000001.SH",  # 上证综指（60 开头）
    "399001.SZ",  # 深证成指（00 开头）
    "399006.SZ",  # 创业板指（30 开头）
    "000016.SH",  # 上证 50（68 开头兜底）
]


def main():
    parser = argparse.ArgumentParser(description="Fetcher 数据下载测试")
    parser.add_argument("--source", default="tushare",
                        choices=["tushare", "akshare", "baostock"],
                        help="数据源 (默认 tushare；baostock 已弃用)")
    parser.add_argument("--symbol", default=None, help="股票代码，不传则拉取全量")
    parser.add_argument("--start", default=None, help="开始日期 YYYY-MM-DD (默认近30天)")
    parser.add_argument("--end", default=None, help="结束日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--list", action="store_true", help="测试获取全市场股票列表")
    parser.add_argument("--include-index", action="store_true",
                        help="全量下载完后顺手拉取 4 个板块基准指数 (仅 tushare)")
    parser.add_argument("--retry", action="store_true",
                        help="读取 output/download_k_fail/ 下最新失败 JSON 并续传 (仅 tushare)")
    args = parser.parse_args()

    end_date = args.end or datetime.now().strftime("%Y-%m-%d")
    start_date = args.start or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    source = args.source
    fetcher = _create_fetcher(source)

    print(f"数据源: {source}")
    print(f"股票: {args.symbol or '全量'}")
    print(f"区间: {start_date} ~ {end_date}")
    print("=" * 50)

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

    # 测试3: 下载数据
    if args.symbol:
        # 指定股票：只下载单只
        print(f"\n[测试3] 下载 {args.symbol} K线数据")
        fetch_start = start_date.replace("-", "")
        fetch_end = end_date.replace("-", "")

        if args.symbol.startswith("idx_"):
            # 指数：idx_000001_SH → 000001.SH
            ts_code = args.symbol[4:].replace("_", ".")
            from api.fetcher.tushare_fetcher import TushareDataFetcher
            ts_fetcher = TushareDataFetcher()
            df = ts_fetcher.fetch_index(ts_code, fetch_start, fetch_end)
        else:
            df = fetcher._fetch_single_stock(args.symbol, fetch_start, fetch_end)

        if df is not None and not df.empty:
            fetcher._save_stock_data(args.symbol, df)
            print(f"  下载成功: {len(df)} 条记录")
        else:
            print(f"  未获取到数据")

        # 验证结果
        _print_csv_result(args.symbol)
    elif args.retry:
        # 续传模式：读取最新失败 JSON
        print(f"\n[测试3] 续传模式")
        retry_symbols = _load_latest_failed_symbols()
        if not retry_symbols:
            print("  未找到失败记录，无需续传")
            return
        print(f"  找到 {len(retry_symbols)} 只待续传")
        result = fetcher.fetch(start_date=start_date, end_date=end_date, symbols=retry_symbols)
        _maybe_fetch_indices(args, fetcher, start_date, end_date, result=result)
    else:
        # 未指定股票：拉取全量
        print(f"\n[测试3] 拉取全量 K线数据")
        result = fetcher.fetch(start_date=start_date, end_date=end_date)
        _maybe_fetch_indices(args, fetcher, start_date, end_date, result=result)


def _maybe_fetch_indices(args, fetcher, start_date: str, end_date: str, result):
    """根据 --include-index 选项追加下载 4 个板块基准指数"""
    if not args.include_index:
        return
    if args.source != "tushare":
        print("\n--include-index 仅支持 tushare 数据源，跳过")
        return

    print(f"\n[测试4] 下载板块基准指数 ({len(DEFAULT_INDICES)} 个)")
    fetch_start = start_date.replace("-", "")
    fetch_end = end_date.replace("-", "")
    for ts_code in DEFAULT_INDICES:
        symbol = f"idx_{ts_code.replace('.', '_')}"
        print(f"  下载 {symbol} ({ts_code}) ...", end=" ", flush=True)
        df = fetcher.fetch_index(ts_code, fetch_start, fetch_end)
        if df is not None and not df.empty:
            fetcher._save_stock_data(symbol, df)
            print(f"OK ({len(df)} 条)")
        else:
            print("无数据")


def _load_latest_failed_symbols() -> list:
    """读取 output/download_k_fail/ 下最新一份 JSON 的失败股票列表"""
    from api.config import settings
    fail_dir = os.path.join(settings.OUTPUT_DIR, "download_k_fail")
    if not os.path.isdir(fail_dir):
        return []
    files = sorted(glob.glob(os.path.join(fail_dir, "*.json")))
    if not files:
        return []
    latest = files[-1]
    print(f"  读取失败记录: {latest}")
    with open(latest, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return [item["symbol"] for item in payload.get("failures", [])]


def _print_csv_result(symbol: str):
    """打印下载结果"""
    import pandas as pd
    csv_path = os.path.join("data", f"{symbol}.csv")
    if os.path.exists(csv_path):
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
        from api.fetcher.tushare_fetcher import TushareDataFetcher
        return TushareDataFetcher()
    elif source == "akshare":
        from api.fetcher.akshare_fetcher import AkShareDataFetcher
        return AkShareDataFetcher()
    else:
        print("⚠️ BaoStock 已弃用（服务器长期不稳定），建议改用 --source akshare")
        from api.fetcher.baostock_fetcher import BaoStockDataFetcher
        return BaoStockDataFetcher()


if __name__ == "__main__":
    main()
