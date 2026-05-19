# A 股量化交易回测系统

基于 vnpy 框架的 A 股量化交易回测平台，支持策略代码化、回测分析和参数优化。

## 功能特点

- 📊 数据源：AkShare（默认，免费，基于东方财富）/ Tushare（私有代理）
- 🎯 策略框架：基于 vnpy CTA 策略模板，回测与实盘代码统一
- 📈 技术指标：KDJ、知行趋势、振幅等，支持自定义扩展
- 💾 回测引擎：vnpy BacktestingEngine，内置 A 股交易规则（T+1、涨跌停、最小交易单位）
- 📉 可视化：净值曲线、回撤曲线、每日盈亏图表
- 🚀 参数优化：网格搜索最优参数组合

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 下载数据并导入 vnpy 数据库

```bash
python main.py data --start 2024-01-01 --end 2025-12-31
```

### 2. 单股回测

```bash
python main.py backtest --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30
```

### 3. 参数优化

```bash
python main.py optimize --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30
```

## 项目结构

```
stock_quant/
├── config/                  # 配置模块
│   └── settings.py          # 回测参数、费用配置、可视化配置
├── data/                    # 股票 CSV 数据
├── fetcher/                 # 数据获取模块
│   ├── fetcher.py             # 数据获取基类
│   ├── akshare_fetcher.py     # AkShare 数据源实现（推荐）
│   ├── tushare_fetcher.py     # Tushare 数据源实现
│   └── baostock_fetcher.py    # BaoStock 数据源实现（已弃用）
├── adapter/                 # 数据适配层
│   └── vnpy_adapter.py      # CSV → vnpy BarData 转换
├── indicator/               # 技术指标计算
│   └── indicators.py        # KDJ、知行趋势、振幅 + IndicatorCalculator 桥接层
├── strategy/                # 交易策略
│   ├── base_strategy.py     # 策略基类（继承 vnpy CtaTemplate）
│   └── b1.py                # B1 策略示例（KDJ + 知行趋势）
├── backtest/                # 回测模块
│   ├── engine.py            # 回测引擎封装
│   └── reporter.py          # 回测报告 + 可视化
├── reports/                 # 回测报告输出目录
├── utils/                   # 工具函数
├── main.py                  # 主程序入口
└── requirements.txt         # 依赖包
```

## 编写自定义策略

### 步骤 1：创建策略文件

在 `strategy/` 目录下创建新策略文件，例如 `my_strategy.py`：

```python
from vnpy.trader.object import BarData
from strategy.base_strategy import BaseStrategy


class MyStrategy(BaseStrategy):
    """我的自定义策略"""

    author = "your_name"

    # 策略参数
    fast_window = 10
    slow_window = 20

    parameters = ["fast_window", "slow_window"]
    variables = []

    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        """策略逻辑"""
        # 获取指标
        kdj = self.indicator.kdj()
        zx = self.indicator.zx_trend()

        # 买入条件
        if self.pos == 0 and not at_upper_limit:
            # 在这里编写买入条件
            if kdj["J"] < 20:
                self.buy_stock(bar.close_price, 100)

        # 卖出条件
        if self.pos > 0 and can_sell and not at_lower_limit:
            # 在这里编写卖出条件
            if kdj["J"] > 80:
                self.sell_stock(bar.close_price, abs(self.pos))
```

### 步骤 2：在 main.py 中注册策略

修改 `main.py` 中的 `strategy_map`：

```python
strategy_map = {
    "b1": B1Strategy,
    "my": MyStrategy,  # 新增
}
```

### 步骤 3：运行回测

```bash
python main.py backtest --strategy my --symbol 600000 --start 2024-01-01 --end 2025-06-30
```

## 策略接口说明

### BaseStrategy 基类

所有策略继承 `BaseStrategy`，需实现 `execute_logic` 方法：

```python
def execute_logic(self, bar: BarData, can_sell: bool,
                  at_upper_limit: bool, at_lower_limit: bool):
    """
    策略逻辑
    :param bar: 当前 K 线数据
    :param can_sell: 是否可以卖出（T+1 限制）
    :param at_upper_limit: 是否涨停
    :param at_lower_limit: 是否跌停
    """
    pass
```

### 可用指标

通过 `self.indicator` 调用：

- `kdj(n=9, m1=3, m2=3)` → `{"K": ..., "D": ..., "J": ..., "RSV": ...}`
- `zx_trend()` → `{"zx_short": ..., "zx_long": ..., "white": ..., "yellow": ..., "bbi": ..., "didi": ...}`
- `amplitude()` → `float`

### 交易方法

- `self.buy_stock(price, volume)` — 买入（自动处理最小 100 股）
- `self.sell_stock(price, volume)` — 卖出（自动处理最小 100 股）
- `self.pos` — 当前持仓（正数为多头，0 为空仓）

## 内置策略说明

### B1 策略

选股条件：
- KDJ 的 J 值 < 13（低位）
- 趋势白线在黄线上方
- 收盘价在黄线 -1% 之上
- 未涨停

卖出条件：
- KDJ 的 J 值 > 80（高位）
- 满足 T+1（次日可卖）
- 未跌停

## A 股交易规则

系统内置以下 A 股特有规则：

- **T+1 限制**：当日买入次日才能卖出
- **涨跌停限制**：涨停无法买入、跌停无法卖出
  - 主板：±10%
  - 创业板/科创板：±20%
  - ST 股票：±5%
- **最小交易单位**：1 手 = 100 股

## 回测配置

在 `config/settings.py` 中修改回测参数：

```python
BACKTEST_CONFIG = {
    "capital": 100000,      # 初始资金
    "rate": 0.001,          # 综合费率（简化模型）
    "slippage": 0.01,       # 滑点
    "size": 1,              # 合约乘数
    "pricetick": 0.01,      # 最小价格变动
    "interval": "daily",    # K 线周期
}
```

## 注意事项

1. **数据准备**：首次使用需先运行 `python main.py data` 下载数据
2. **回测周期**：建议回测周期至少 6 个月，以获得统计意义
3. **参数优化**：避免过度拟合，优化后需在样本外数据验证
4. **实盘对接**：当前版本仅支持回测，实盘功能后续开发

## 许可证

MIT License
