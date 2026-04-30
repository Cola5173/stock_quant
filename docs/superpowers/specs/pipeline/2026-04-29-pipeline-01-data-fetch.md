# 环节 1：数据拉取

> 上游依赖：无（流水线起点）
> 下游消费：环节 2（筛选 + K线图生成）
> 输入：BaoStock API
> 输出：`data/*.csv`、`data/vnpy_db.sqlite`、`data/stock_extra_info.json`

## 1. 概述

复用现有 `fetcher/` 和 `adapter/` 模块，无需新建代码。本环节文档记录数据拉取的完整流程和接口，供下游环节和调度器参考。

## 2. 现有模块复用

### 2.1 BaoStockDataFetcher（fetcher/baostock_fetcher.py）

- 从 BaoStock API 下载日 K 线数据
- 支持增量更新（自动检测本地数据最新日期，只下载缺失部分）
- 保存为 CSV 格式到 `data/` 目录
- 数据字段：date, code, open, high, low, close, preclose, volume, amount, adjustflag, turn, tradestatus, pctChg, isST
- 复权方式：前复权（`adjustflag="2"`）

### 2.2 VnpyAdapter（adapter/vnpy_adapter.py）

- 将 CSV 数据转换为 vnpy BarData 格式
- 导入到 vnpy SQLite 数据库（`data/vnpy_db.sqlite`）
- 校验 OHLC 数据合理性（high ≥ low, high ≥ open/close 等）
- 提取 A 股特有字段（isST、tradestatus）到 `data/stock_extra_info.json`

## 3. 全市场股票列表

**来源：** 使用 BaoStock API 的 `query_stock_basic()` 获取全市场股票列表

**过滤条件：** 剔除 ST、退市、停牌股票

**更新频率：** 每次扫描前自动更新

**存储：** Scanner 初始化时从 BaoStock 实时获取，或从缓存文件 `data/stock_list.csv` 读取

## 4. CLI 命令

```bash
# 下载数据并导入 vnpy 数据库
python main.py data --start 2024-01-01 --end 2025-12-31

# 增量更新（自动检测缺失日期并补齐）
python main.py data --start 2024-01-01 --end 2025-12-31
```

## 5. 错误处理

**重试策略：**
- 3 次重试，指数退避（1s, 2s, 4s）
- 超时设置：30 秒/请求

**失败处理：**
- 记录失败股票列表到 `logs/data_fetch_error.log`
- 跳过该股票，继续处理下一个
- 如果失败率 > 20%，发送告警

## 6. 数据格式

### CSV 文件（data/{symbol}.csv）

| 字段 | 类型 | 说明 |
|------|------|------|
| date | datetime | 交易日期 |
| code | string | 股票代码（sh.600000） |
| open | float | 开盘价 |
| high | float | 最高价 |
| low | float | 最低价 |
| close | float | 收盘价 |
| preclose | float | 前收盘价 |
| volume | float | 成交量 |
| amount | float | 成交额 |
| turn | float | 换手率（%） |
| tradestatus | string | 交易状态（1=正常，0=停牌） |
| pctChg | float | 涨跌幅（%） |
| isST | string | 是否 ST（1=是，0=否） |

### stock_extra_info.json

```json
{
  "600000": {"is_st": false},
  "000001": {"is_st": false}
}
```
