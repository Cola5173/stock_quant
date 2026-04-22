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
├── indicator/               # 指标计算（重构：桥接层，复用现有 pandas 计算逻辑）
│   └── indicators.py        # IndicatorCalculator 桥接 ArrayManager → DataFrame
├── strategy/                # 策略（重构）
│   ├── base_strategy.py     # 继承 vnpy CtaTemplate
│   └── b1.py                # 适配 vnpy 策略接口
├── backtest/                # 新增：回测模块
│   ├── engine.py            # 封装 vnpy BacktestingEngine
│   └── reporter.py          # 回测报告 + 可视化图表
├── reports/                 # 新增：回测报告输出目录
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

**数据校验（失败处理策略）：**
- 检查 OHLC 合理性（high >= low, high >= open/close, low <= open/close）→ 不合理的记录跳过并记录日志
- 检查交易日连续性，记录缺失日期 → 仅记录警告日志，不阻断导入
- 过滤 volume=0 的停牌日数据 → 跳过，不导入 vnpy 数据库

**A 股特有字段处理：**
- `isST`、`tradestatus` 等字段不写入 vnpy BarData（无对应字段）
- 导出为独立映射文件 `data/stock_extra_info.json`，格式：`{"600000": {"is_st": false, ...}}`
- 策略初始化时加载该映射文件

**复权处理：**
- 保持现有 BaoStock 前复权数据（`adjustflag="2"`），不做二次处理

### 2. 指标层重构（indicator/indicators.py）

改造方式：保留现有 pandas 向量化计算逻辑不变，`IndicatorCalculator` 作为桥接层，将 ArrayManager 的 numpy 数组转为 DataFrame 后调用现有计算函数。

```python
class IndicatorCalculator:
    def __init__(self, am: ArrayManager):
        self.am = am
        self._df = self._am_to_dataframe()

    def _am_to_dataframe(self) -> pd.DataFrame:
        """将 ArrayManager 的 numpy 数组转为 DataFrame，复用现有指标函数"""
        return pd.DataFrame({
            "open": self.am.open_array,
            "close": self.am.close_array,
            "high": self.am.high_array,
            "low": self.am.low_array,
            "volume": self.am.volume_array,
        })

    def kdj(self, n=9, m1=3, m2=3) -> dict:
        # 内部调用现有 calculate_KDJ(self._df, n, m1, m2)
        return {"k": k, "d": d, "j": j}

    def zx_trend(self) -> dict:
        # 内部调用现有 calculate_zx_trend(self._df)
        # 统一返回 key 命名：zx_short, zx_long, white, yellow, bbi, didi
        return {...}

    def amplitude(self) -> float:
        # 内部调用现有 calculate_amplitude(self._df)
        return amp
```

这样做的好处：
- 现有指标计算函数（pandas 向量化）完全保留，不重写
- ArrayManager → DataFrame 转换开销很小（numpy 数组直接构造）
- 新增指标可以选择用 pandas 或直接用 numpy 数组
- 返回值 key 统一为简短命名（`white`/`yellow` 而非 `zx_trend_white`/`zx_trend_yellow`）

### 3. 策略层重构（strategy/）

现有 `BaseStrategy` 是选股策略（`select(trade_date) → Set[str]`），vnpy 的 `CtaTemplate` 是交易策略（逐 bar 触发买卖信号）。两者是不同范式，重构后完全替换为 vnpy 交易策略体系，现有选股接口废弃。

**策略迁移指南：**
- 现有选股逻辑（"满足条件 → 加入候选列表"）转换为交易信号（"满足条件 → 买入；不满足 → 卖出"）
- 选股条件直接映射为买入条件，需额外设计卖出条件（止盈/止损/信号反转）
- 现有 `select_one(stock_code, trade_date)` 的判断逻辑可直接复用到 `execute_logic()` 中

**base_strategy.py** — 继承 vnpy 的 `CtaTemplate`：

```python
class BaseStrategy(CtaTemplate):
    def __init__(self, cta_engine, strategy_name, vt_symbol, setting):
        super().__init__(cta_engine, strategy_name, vt_symbol, setting)
        self.bg = BarGenerator(self.on_bar)
        self.am = ArrayManager(size=200)          # 需覆盖 MA(114) 等长周期指标
        self.indicator = None
        self.buy_date = None                       # T+1 限制：记录买入日期

    def on_init(self):
        self.load_bar(200)

    def on_bar(self, bar: BarData):
        self.am.update_bar(bar)
        if not self.am.inited:
            return
        self.indicator = IndicatorCalculator(self.am)

        # T+1 检查：当日买入不可卖出
        can_sell = (self.buy_date is not None and bar.datetime.date() > self.buy_date)
        self.execute_logic(bar, can_sell)

    def execute_logic(self, bar: BarData, can_sell: bool):
        raise NotImplementedError

    def buy(self, price, volume, **kwargs):
        # 最小交易单位：向下取整到 100 股（vnpy volume 单位为股）
        volume = (volume // 100) * 100
        if volume > 0:
            self.buy_date = bar.datetime.date()
            super().buy(price, volume, **kwargs)
```

**b1.py** — 策略示例：

```python
class B1Strategy(BaseStrategy):
    kdj_n = 9
    kdj_j_threshold = 13
    parameters = ["kdj_n", "kdj_j_threshold"]

    def execute_logic(self, bar: BarData, can_sell: bool):
        kdj = self.indicator.kdj(n=self.kdj_n)
        zx = self.indicator.zx_trend()
        if kdj["j"] < self.kdj_j_threshold and zx["white"] > zx["yellow"]:
            self.buy(bar.close_price, 100)
        if can_sell and kdj["j"] > 80:
            self.sell(bar.close_price, 1)
```

- 所有策略继承 `BaseStrategy`，只需实现 `execute_logic()`
- 策略参数通过 `parameters` 列表声明，支持回测参数优化
- `BarGenerator` 支持从日线合成周线/月线，天然支持多周期
- 同一策略代码，回测和未来实盘零改动

### 3.1 A 股交易规则处理

回测引擎需处理以下 A 股特有规则：

**T+1 限制**：在 `BaseStrategy` 中维护 `buy_date`，`on_bar` 中比较当前日期判断是否可卖出（见上方代码）。

**涨跌停限制**：在 `execute_logic()` 中根据涨跌幅过滤：
```python
pct_change = (bar.close_price - prev_close) / prev_close
# 根据股票代码前缀判断涨跌停幅度
if symbol.startswith("30") or symbol.startswith("68"):
    limit = 0.20    # 创业板/科创板 ±20%
elif is_st:
    limit = 0.05    # ST 股票 ±5%
else:
    limit = 0.10    # 主板 ±10%
at_upper_limit = pct_change >= limit - 0.001
at_lower_limit = pct_change <= -limit + 0.001
# 涨停不买入，跌停不卖出
```

**最小交易单位**：vnpy 的 `volume` 单位为股，在 `BaseStrategy.buy()` 中向下取整到 100 的整数倍。

**ST 股票过滤**：adapter 导入数据时，将 `isST` 字段存入独立的映射表（`data/st_mapping.json`），策略初始化时加载。

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
    "rate": 0.001,            # 简化费率：佣金万三(双向) + 印花税千一(单向) ≈ 综合千一
    "slippage": 0.01,         # 固定滑点 1 分钱（A 股最小价格变动）
    "size": 1,                # vnpy size=1 表示 1 股为单位
    "pricetick": 0.01,
    "interval": "daily",
}

# A 股费用明细（后续精细化时替换 rate 为自定义费用计算函数）
FEE_CONFIG = {
    "commission_rate": 0.0003,    # 佣金万三（买卖双向，最低 5 元）
    "stamp_tax_rate": 0.001,      # 印花税千一（仅卖出）
    "transfer_fee_rate": 0.00001, # 过户费十万分之一（仅沪市）
    "min_commission": 5.0,        # 最低佣金 5 元
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
| indicator/ | 重构 | 新增 IndicatorCalculator 桥接层，复用现有 pandas 计算函数 |
| strategy/ | 重构 | 继承 CtaTemplate |
| backtest/ | 新增 | 回测引擎 + 可视化报告 |
| model/ | 保留 | 重构后由 adapter 和 indicator 替代字段访问，保留作为数据源字段映射参考 |
| utils/ | 保留 | 不动 |
| main.py | 重构 | argparse 子命令入口 |

## 依赖新增

```
vnpy==3.9.0
vnpy-ctastrategy>=1.0.0
matplotlib>=3.7.0
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
