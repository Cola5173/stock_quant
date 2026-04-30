"""
测试全市场股票列表获取功能
"""
from fetcher.baostock_fetcher import BaoStockDataFetcher

def test_get_stock_list():
    """测试获取股票列表"""
    fetcher = BaoStockDataFetcher()

    # 获取股票列表（过滤ST和停牌）
    stock_list = fetcher.get_all_stock_list(
        filter_st=True,
        filter_suspended=True,
        cache_file="data/stock_list.csv"
    )

    print(f"\n获取到 {len(stock_list)} 只股票")
    print(f"前10只股票: {stock_list[:10]}")

    # 验证缓存文件
    import os
    if os.path.exists("data/stock_list.csv"):
        with open("data/stock_list.csv", 'r') as f:
            lines = f.readlines()
            print(f"\n缓存文件包含 {len(lines)} 只股票")

    return stock_list

if __name__ == "__main__":
    test_get_stock_list()
