# Fetcher 数据获取模块

负责从不同数据源拉取 A 股日线数据，统一输出为 CSV 格式存储到 `data/` 目录。

## 使用示例

```bash
# 单只股票
python api/fetcher/test_fetcher.py --source tushare --symbol 600000 --start 2024-01-01

# 全量下载（不传 --symbol）
python api/fetcher/test_fetcher.py --source tushare --start 2024-01-01

# 指数下载（idx_ 前缀）
python api/fetcher/test_fetcher.py --source tushare --symbol idx_000001_SH --start 2023-01-01
python api/fetcher/test_fetcher.py --source tushare --symbol idx_399006_SZ --start 2023-01-01
python api/fetcher/test_fetcher.py --source tushare --symbol idx_883957_TI --start 2023-01-01

# 使用 akshare 数据源
python api/fetcher/test_fetcher.py --source akshare --symbol 000001 --start 2025-01-01

# 获取全市场股票列表
python api/fetcher/test_fetcher.py --source tushare --list
```

## 数据源

| 数据源 | 类 | 说明 |
|--------|-----|------|
| Tushare | `TushareDataFetcher` | 私有代理，速度快，推荐 |
| AkShare | `AkShareDataFetcher` | 免费，基于东方财富，偶发限流 |
| BaoStock | `BaoStockDataFetcher` | 免费，稳定，速度较慢 |

## 文件说明

| 文件 | 职责 |
|------|------|
| `fetcher.py` | 基类 `DataFetcher`，定义统一接口和 CSV 读写逻辑 |
| `tushare_client.py` | Tushare Pro 客户端初始化（token + 代理 URL + pandas 兼容 patch） |
| `tushare_fetcher.py` | Tushare 数据源实现 |
| `akshare_fetcher.py` | AkShare 数据源实现 |
| `baostock_fetcher.py` | BaoStock 数据源实现 |
| `test_fetcher.py` | 测试脚本，支持单只/全量下载 |

## 统一接口

所有 Fetcher 继承 `DataFetcher`，必须实现：

- `get_last_trade_date() -> str` — 获取最近交易日
- `fetch(start_date, end_date)` — 批量下载（读取 `resource/stock_code.csv`）
- `_fetch_single_stock(symbol, start_YYYYMMDD, end_YYYYMMDD)` — 下载单只股票
- `get_all_stock_list(filter_st) -> List[str]` — 获取全市场股票列表

## 增量逻辑

`fetch()` 会检查本地 CSV 已有数据范围，自动计算需要拉取的区间：
- 本地 min_date 晚于请求 start 超过 3 天：向前回填
- 本地 max_date 早于请求 end：向后增量
- 两端都已覆盖：跳过
