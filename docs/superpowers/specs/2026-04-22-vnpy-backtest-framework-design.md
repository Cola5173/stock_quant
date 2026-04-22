# A 股量化交易回测框架设计文档

## 概述

基于 vnpy 框架，将现有 A 股量化选股系统升级为支持**策略代码化 → 回测 → 可视化分析**的完整回测平台。架构设计兼容未来实盘自动交易的接入。

## 需求

- 市场：仅 A 股现货
- 交易风格：多周期策略并存（短线/中线/中长线）
- 当前阶段：策略框架 + 回测能力，策略后续逐步添加
- 回测输出：基础指标（收益率、年化、最大回撤、夏普比率、胜率）+ 可视化图表（收益曲线、回撤曲线、每日盈亏、持仓分布）
- 未来目标：对接券商（广发证券/中信建投）实现实盘自动交易

## 架构总览

```
stock_quant/
├── config/                  # 配置（保留，扩展）
│   └── settings.py          # 新增 vnpy 相关配置（手续费、滑点等）
├── data/                    # 股票 CSV 数据（保留）
├── fetcher/                 # 数据获取（保留，不动）
│   ├── fetcher.py
│   └── baostock_fetcher.py
├── adapter/                 # 新增：数据适配层
│   └── vnpy_adapter.py      # CSV 数据 → vnpy BarData 转换
├── indicator/               # 指标计算（重构）
│   └── indicators.py        # 用 vnpy ArrayManager 重写
├── strategy/                # 策略（重构）
│   ├── base_strategy.py     # 继承 vnpy CtaTemplate
│   └── b1.py                # 适配 vnpy 策略接口
├── backtest/                # 新增：回测模块
│   ├── engine.py            # 封装 vnpy BacktestingEngine
│   └── reporter.py          # 回测报告 + 可视化图表
├── utils/                   # 工具（保留，不动）
├── main.py                  # 入口重构（argparse 子命令）
└── requirements.txt         # 新增 vnpy 依赖
```

## 模块详细设计

### 1. 数据适配层（adapter/vnpy_adapter.py）

职责：连接现有 BaoStock CSV 数据和 vnpy 回测引擎。

功能：
- 读取 `data/` 目录下的 CSV 文件（BaoStock 格式）
- 转换为 vnpy 的 `BarData` 对象列表
- 通过 vnpy 的 `database_manager`（`vnpy.trader.database.get_database()`）写入数据库，供回测引擎读取

字段映射：

| 现有字段（kline_constants） | vnpy BarData 字段 |
|---|---|
| date | datetime |
| open | open_price |
| close | close_price |
| high | high_price |
| low | low_price |
| volume | volume |
| amount | turnover |

股票代码转换规则：
- `sh.600000` → `Exchange.SSE` + `symbol="600000"`
- `sz.000001` → `Exchange.SZSE` + `symbol="000001"`

支持批量导入和增量更新（只导入新数据）。K 线周期以日线为主，后续可扩展分钟线。

**数据校验：**
- 检查 OHLC 合理性（high >= low, high >= open/close, low <= open/close）
- 检查交易日连续性，记录缺失日期
- 过滤 volume=0 的停牌日数据

**复权处理：**
- 保持现有 BaoStock 前复权数据（`adjustflag="2"`），不做二次处理

### 2. 指标层重构（indicator/indicators.py）

改造方式：保留现有指标计算逻辑，用 vnpy 的 `ArrayManager` 作为数据容器。

```python
class IndicatorCalculator:
    def __init__(self, am: ArrayManager):
        self.am = am

    def kdj(self, n=9, m1=3, m2=3) -> dict:
        # 复用现有 KDJ 算法，数据源从 am 获取
        return {"k": k, "d": d, "j": j}

    def zx_trend(self) -> dict:
        # 知行短期/长期、趋势白线、大哥黄线、BBI、滴滴战法
        return {"zx_short": ..., "zx_long": ..., "white": ..., "yellow": ..., "bbi": ..., "didi": ...}

    def amplitude(self) -> float:
        # (high - low) / low * 100
        return amp
```

- 策略中通过 `self.am`（ArrayManager）直接调用指标
- 新增指标只需在 `IndicatorCalculator` 中加方法
- ArrayManager 自动维护固定长度的 K 线窗口，内存可控

### 3. 策略层重构（strategy/）

**base_strategy.py** — 继承 vnpy 的 `CtaTemplate`：

```python
class BaseStrategy(CtaTemplate):
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=200)          # 需覆盖 MA(114) 等长周期指标
        self.indicator = None

    def on_init(self):
        self.load_bar(200)

    def on_bar(self, bar: BarData):
        self.am.update_bar(bar)
        if not self.am.inited:
            return
        self.indicator = IndicatorCalculator(self.am)
        self.execute_logic(bar)

    def execute_logic(self, bar: BarData):
        raise NotImplementedError
```

**b1.py** — 策略示例：

```python
class B1Strategy(BaseStrategy):
    kdj_n = 9
    kdj_j_threshold = 13
    parameters = ["kdj_n", "kdj_j_threshold"]

    def execute_logic(self, bar: BarData):
        kdj = self.indicator.kdj(n=self.kdj_n)
        zx = self.indicator.zx_trend()
        if kdj["j"] < self.kdj_j_threshold and zx["white"] > zx["yellow"]:
            self.buy(bar.close_price, 1)
        if kdj["j"] > 80:
            self.sell(bar.close_price, 1)
```

- 所有策略继承 `BaseStrategy`，只需实现 `execute_logic()`
- 策略参数通过 `parameters` 列表声明，支持回测参数优化
- `BarGenerator` 支持从日线合成周线/月线，天然支持多周期
- 同一策略代码，回测和未来实盘零改动

### 3.1 A 股交易规则处理

回测引擎需处理以下 A 股特有规则：
- **T+1 限制**：当日买入次日才能卖出，在 `BaseStrategy` 中维护买入日期，`on_bar` 中检查持仓天数
- **涨跌停限制**：涨停时无法买入、跌停时无法卖出，通过判断当日涨跌幅是否触及 ±10%（创业板/科创板 ±20%）来过滤
- **最小交易单位**：1 手 = 100 股，下单量向下取整到 100 的整数倍
- **ST 股票过滤**：利用现有数据中的 `isST` 字段，默认跳过 ST 股票

### 4. 回测模块（backtest/）

**engine.py** — 回测引擎封装：

```python
class BacktestRunner:
    def __init__(self, strategy_class, vt_symbol, start, end, setting=None):
        self.engine = BacktestingEngine()
        self.engine.set_parameters(
            vt_symbol=vt_symbol,
            interval=Interval.DAILY,
            start=start, end=end,
            rate=0.0003, slippage=0.01,
            size=100, pricetick=0.01,
            capital=100000,
        )
        self.engine.add_strategy(strategy_class, setting or {})

    def run(self):
        self.engine.load_data()
        self.engine.run_backtesting()
        self.engine.calculate_result()            # 必须先调用，生成逐日盈亏
        return self.engine.calculate_statistics()  # 再调用，生成统计指标

    def optimize(self, setting: OptimizationSetting) -> list:
        return self.engine.run_optimization(setting)
```

**reporter.py** — 回测报告 + 可视化：

```python
class BacktestReporter:
    def __init__(self, engine: BacktestingEngine):
        self.engine = engine

    def summary(self) -> dict:
        return self.engine.calculate_statistics()

    def plot(self, save_path=None):
        # 1. 收益曲线（净值 vs 基准）
        # 2. 回撤曲线
        # 3. 每日盈亏柱状图
        # 4. 持仓分布饼图
```

- vnpy `calculate_statistics()` 自带十几项指标
- 可视化用 matplotlib，支持保存为图片到 `reports/` 目录

### 5. 配置扩展（config/settings.py）

```python
# 现有配置保留

# 新增：vnpy 数据库配置
VNPY_DB_PATH = "data/vnpy_db.sqlite"

# 新增：回测默认参数
BACKTEST_CONFIG = {
    "capital": 100000,
    "rate": 0.0003,           # 佣金万三（买卖双向）
    "slippage": 0.01,
    "size": 100,
    "pricetick": 0.01,
    "interval": "daily",
}

# A 股费用明细（用于自定义费用计算，后续精细化）
FEE_CONFIG = {
    "commission_rate": 0.0003,    # 佣金万三（买卖双向）
    "stamp_tax_rate": 0.001,      # 印花税千一（仅卖出）
    "transfer_fee_rate": 0.00001, # 过户费十万分之一（仅沪市）
}

# 新增：可视化配置
REPORT_DIR = "reports"
PLOT_STYLE = "seaborn-v0_8-darkgrid"
```

### 6. 主程序入口（main.py）

使用 `argparse` 子命令：

```bash
# 更新数据并导入 vnpy
python main.py data --start 2024-01-01 --end 2025-12-31

# 单股回测
python main.py backtest --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30

# 参数优化
python main.py optimize --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30

# 批量选股回测（后续扩展）
python main.py scan --strategy b1 --start 2024-01-01 --end 2025-06-30
```

## 改动总览

| 模块 | 改动类型 | 说明 |
|---|---|---|
| config/ | 扩展 | 新增回测和 vnpy 配置 |
| fetcher/ | 保留 | 不动 |
| adapter/ | 新增 | CSV → vnpy BarData 桥接 |
| indicator/ | 重构 | 用 ArrayManager 重写 |
| strategy/ | 重构 | 继承 CtaTemplate |
| backtest/ | 新增 | 回测引擎 + 可视化报告 |
| model/ | 保留 | 重构后由 adapter 和 indicator 替代字段访问，保留作为数据源字段映射参考 |
| utils/ | 保留 | 不动 |
| main.py | 重构 | argparse 子命令入口 |

## 依赖新增

```
vnpy>=3.0.0
vnpy-ctastrategy
matplotlib>=3.5.0
```

## 完整调用流程示例

```python
# main.py backtest 子命令的执行流程
from backtest.engine import BacktestRunner
from backtest.reporter import BacktestReporter
from strategy.b1 import B1Strategy

# 1. 创建回测运行器
runner = BacktestRunner(
    strategy_class=B1Strategy,
    vt_symbol="600000.SSE",
    start=datetime(2024, 1, 1),
    end=datetime(2025, 6, 30),
    setting={"kdj_n": 9, "kdj_j_threshold": 13}
)

# 2. 运行回测（内部流程）
#    → engine.load_data() 从 vnpy 数据库加载数据（adapter 已导入）
#    → engine.run_backtesting()
#      → 逐 bar 调用 B1Strategy.on_bar()
#        → am.update_bar(bar)
#        → IndicatorCalculator(am).kdj() / zx_trend()
#        → self.buy() / self.sell()
#    → engine.calculate_result() 生成逐日盈亏 DataFrame
#    → engine.calculate_statistics() 生成统计指标 dict
stats = runner.run()

# 3. 生成报告和可视化
reporter = BacktestReporter(runner.engine)
reporter.summary()  # 打印统计指标
reporter.plot(save_path="reports/b1_600000.png")  # 保存图表
```
