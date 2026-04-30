"""
测试全市场股票列表获取功能
支持选择不同的数据源：akshare 或 baostock
"""
import argparse


def test_get_stock_list(source: str = "akshare"):
    """
    测试获取股票列表
    :param source: 数据源 (akshare 或 baostock)
    """
    if source == "akshare":
        from fetcher.akshare_fetcher import AkShareDataFetcher
        fetcher = AkShareDataFetcher()
        cache_file = "data/stock_list_akshare.csv"

        # AkShare 不支持过滤停牌，只过滤 ST
        stock_list = fetcher.get_all_stock_list(
            filter_st=True,
            cache_file=cache_file
        )
    else:
        from fetcher.baostock_fetcher import BaoStockDataFetcher
        fetcher = BaoStockDataFetcher()
        cache_file = "data/stock_list_baostock.csv"

        # BaoStock 支持过滤 ST 和停牌
        stock_list = fetcher.get_all_stock_list(
            filter_st=True,
            filter_suspended=True,
            cache_file=cache_file
        )

    print(f"\n数据源: {source}")
    print(f"获取到 {len(stock_list)} 只股票")
    if stock_list:
        print(f"前10只股票: {stock_list[:10]}")

    # 验证缓存文件
    import os
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            lines = f.readlines()
            print(f"\n缓存文件包含 {len(lines)} 只股票")
            print(f"缓存路径: {cache_file}")

    return stock_list


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试股票列表获取")
    parser.add_argument("--source", default="akshare", choices=["akshare", "baostock"],
                        help="数据源 (默认 akshare)")
    args = parser.parse_args()

    test_get_stock_list(args.source)
