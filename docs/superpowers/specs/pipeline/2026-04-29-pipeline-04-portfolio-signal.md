# 环节 4：组合回测 + 信号生成

> 上游依赖：环节 3（LLM 打分）
> 下游消费：环节 5（定时调度）、用户手动执行
> 输入：`output/scores/scores_{date}.json`、`data/vnpy_db.sqlite`
> 输出：`output/portfolio/backtest_{start}_{end}.json`、`output/signals/buy_{date}.json`、`output/signals/sell_{date}.json`

## 1. Portfolio 组合回测模块

### 1.1 职责

将筛选出的股票作为一个组合，模拟轮动持仓策略，评估整体收益。

### 1.2 持仓规则

- 初始资金：100,000 元
- 最大持仓数：10 只股票
- 单只股票仓位：总资金 / 10 = 10,000 元
- 买入时机：T 日收盘后筛选，T+1 日开盘价买入
- 卖出时机：满足策略卖出条件时，T+1 日开盘价卖出

### 1.3 轮动策略

- 每日检查持仓，卖出不符合条件的股票
- 从候选池中按 LLM 分数排序，买入前 N 只（补齐 10 只）
- 如果候选池不足，保持现有持仓

### 1.4 费用计算

- 佣金：0.03%（最低 5 元）
- 印花税：0.1%（仅卖出）
- 过户费：0.001%
- 滑点：0.1%（模拟开盘价偏差）
  - 买入：实际成交价 = 开盘价 × (1 + 0.001)
  - 卖出：实际成交价 = 开盘价 × (1 - 0.001)

### 1.5 核心类

```python
class PortfolioEngine:
    """组合回测引擎"""

    def __init__(self, initial_capital=100000, max_positions=10):
        self.capital = initial_capital
        self.max_positions = max_positions
        self.positions = {}   # {symbol: {shares, cost, buy_date}}
        self.cash = initial_capital
        self.trades = []      # 交易记录
        self.daily_values = [] # 每日净值

    def run(self, start_date, end_date, strategy_class):
        """运行组合回测"""
        for date in self._get_trading_days(start_date, end_date):
            # T 日收盘后的操作（基于 T 日收盘数据）
            # 1. 检查持仓，生成卖出信号
            sell_signals = self._check_sell_signals(date, strategy_class)

            # 2. 扫描候选股票
            candidates = self._scan_candidates(date, strategy_class)

            # 3. 按分数排序，生成买入信号
            buy_signals = self._generate_buy_signals(candidates)

            # T+1 日开盘的操作
            next_date = self._get_next_trading_day(date)
            if next_date > end_date:
                break

            # 4. 执行卖出（T+1 日开盘价）
            self._execute_sells(sell_signals, next_date)

            # 5. 执行买入（T+1 日开盘价）
            self._execute_buys(buy_signals, next_date)

            # 6. 记录 T+1 日净值
            self._record_daily_value(next_date)

        return self._calculate_statistics()

    def _execute_buys(self, signals, date):
        """执行买入"""
        available_slots = self.max_positions - len(self.positions)
        position_size = self.capital / self.max_positions

        for signal in signals[:available_slots]:
            symbol = signal["symbol"]
            price = self._get_open_price(symbol, date)
            shares = int((position_size / price) // 100) * 100

            if shares > 0 and self.cash >= shares * price:
                cost = self._calculate_buy_cost(shares, price)
                self.cash -= cost
                self.positions[symbol] = {
                    "shares": shares,
                    "cost": cost,
                    "buy_date": date
                }
```

### 1.6 输出格式

```json
// output/portfolio/backtest_20260101_20260429.json
{
  "period": {"start": "2026-01-01", "end": "2026-04-29"},
  "statistics": {
    "total_return": 15.8,
    "annual_return": 52.3,
    "max_drawdown": -8.5,
    "sharpe_ratio": 1.85,
    "win_rate": 62.5,
    "total_trades": 48
  },
  "trades": [],
  "daily_values": []
}
```

## 2. 信号生成

### 2.1 买入信号

基于 LLM 打分结果的 TOP 10，生成买入信号：

```json
// output/signals/buy_20260429.json
{
  "date": "2026-04-29",
  "execute_date": "2026-04-30",
  "signals": [
    {
      "symbol": "600000",
      "name": "浦发银行",
      "score": 92,
      "recommendation": "强烈买入",
      "target_price": 9.50,
      "expected_return": 11.5
    }
  ]
}
```

### 2.2 卖出信号

基于持仓股票的策略卖出条件，生成卖出信号：

```json
// output/signals/sell_20260429.json
{
  "date": "2026-04-29",
  "execute_date": "2026-04-30",
  "signals": [
    {
      "symbol": "600001",
      "name": "邯郸钢铁",
      "reason": "KDJ J值 > 80，触发卖出条件",
      "buy_date": "2026-04-20",
      "buy_price": 3.05,
      "current_price": 3.28,
      "profit_pct": 7.5
    }
  ]
}
```

## 3. 存储清理策略

**K 线图清理：**
- 保留最近 30 天的图片
- 自动删除过期文件
- 每天生成约 20MB，每月约 600MB

## 4. CLI 命令

```bash
# 组合回测
python main.py portfolio --strategy b1 --start 2026-01-01 --end 2026-04-29
# 输出: output/portfolio/backtest_20260101_20260429.json

# 生成交易信号
python main.py signal --date 2026-04-29
# 输出: output/signals/buy_20260429.json, sell_20260429.json
```
