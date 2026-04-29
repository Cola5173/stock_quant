# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

A 股量化交易回测平台，基于 vnpy 3.9.0 框架构建。核心特性：
- 数据源：BaoStock（免费、稳定的 A 股数据）
- 策略框架：vnpy CTA 策略模板（回测与实盘代码统一）
- 交易规则：内置 A 股特有规则（T+1、涨跌停、100 股最小交易单位、ST 股票识别）
- 技术指标：KDJ、知行趋势、振幅（可扩展）
- 回测引擎：vnpy BacktestingEngine + 参数优化 + 可视化报告

## 常用命令

### 环境准备
```bash
# 安装依赖（需要 Python 3.8+）
pip install -r requirements.txt

# 验证 vnpy 版本
python3 -c "import vnpy; print(vnpy.__version__)"  # 应输出 3.9.0
```

### 数据管理
```bash
# 下载数据并导入 vnpy 数据库（首次使用必须执行）
python main.py data --start 2024-01-01 --end 2025-12-31

# 增量更新数据（自动检测缺失日期并补齐）
python main.py data --start 2024-01-01 --end 2025-12-31
```

### 回测与优化
```bash
# 单股回测（生成报告到 reports/ 目录）
python main.py backtest --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30

# 参数优化（网格搜索最优参数）
python main.py optimize --strategy b1 --symbol 600000 --start 2024-01-01 --end 2025-06-30
```

### 数据文件位置
- `data/*.csv` - 股票 K 线数据（500+ 只股票）
- `data/vnpy_db.sqlite` - vnpy 数据库（运行 `python main.py data` 后生成）
- `data/stock_extra_info.json` - A 股特有字段映射（isST 状态等）
- `stock_code.csv` - A 股代码列表（sh.600000 格式）
- `reports/*.png` - 回测报告图表

## 核心架构

### 数据流水线
```
BaoStock API → CSV 文件 → vnpy 数据库 → 回测引擎
     ↓              ↓            ↓
  fetcher/    adapter/     backtest/
```

### 模块职责

**1. fetcher/ - 数据获取层**
- `BaoStockDataFetcher` - 从 BaoStock API 下载日 K 线数据
- 支持增量更新（自动检测本地数据最新日期，只下载缺失部分）
- 保存为 CSV 格式到 `data/` 目录

**2. adapter/ - 数据适配层**
- `VnpyAdapter` - 将 CSV 数据转换为 vnpy BarData 格式
- 导入到 vnpy SQLite 数据库（`data/vnpy_db.sqlite`）
- 校验 OHLC 数据合理性（high ≥ low, high ≥ open/close 等）
- 提取 A 股特有字段（isST、tradestatus）到 `stock_extra_info.json`

**3. indicator/ - 技术指标层**
- `indicators.py` - 纯函数实现的技术指标（接受 pandas DataFrame）
  - `calculate_KDJ(df, n=9, m1=3, m2=3)` - KDJ 指标
  - `calculate_zx_trend(df)` - 知行趋势指标（白线、黄线、BBI、DIDI）
  - `calculate_amplitude(df)` - 振幅计算
- `IndicatorCalculator` - 桥接层，将 vnpy ArrayManager 转换为 pandas DataFrame 后调用指标函数

**4. strategy/ - 策略层**
- `BaseStrategy` - 策略基类（继承 vnpy CtaTemplate）
  - 内置 A 股交易规则：
    - T+1 限制：`can_sell` 标志位（当日买入次日才能卖出）
    - 涨跌停检测：`at_upper_limit` / `at_lower_limit`（主板 ±10%，创业板/科创板 ±20%，ST ±5%）
    - 最小交易单位：`buy_stock()` / `sell_stock()` 自动处理 100 股整数倍
  - 指标桥接：`self.indicator` 提供 `kdj()` / `zx_trend()` / `amplitude()` 方法
  - 子类只需实现 `execute_logic(bar, can_sell, at_upper_limit, at_lower_limit)` 方法
- `B1Strategy` - 示例策略（KDJ J < 13 + 白线 > 黄线 买入，J > 80 卖出）

**5. backtest/ - 回测层**
- `BacktestRunner` - 封装 vnpy BacktestingEngine
  - 自动配置回测参数（从 `config/settings.py` 读取）
  - 提供 `run()` 和 `optimize()` 方法
- `BacktestReporter` - 生成统计报告和 matplotlib 可视化图表

**6. config/ - 配置层**
- `settings.py` - 全局配置
  - `BACKTEST_CONFIG` - 回测参数（初始资金、费率、滑点等）
  - `FEE_CONFIG` - A 股费用明细（佣金、印花税、过户费）
  - `REPORT_DIR` - 报告输出目录

### 关键设计决策

**股票代码格式转换**
- BaoStock API 使用 `sh.600000` / `sz.000001` 格式
- vnpy 使用 `600000.SSE` / `000001.SZSE` 格式
- 内部统一使用 6 位纯数字（`600000`）作为文件名和标识符
- 转换函数：`utils.utils._normalize_stock_code()` / `_convert_stock_code()`

**A 股交易规则实现**
- T+1 限制：`BaseStrategy` 维护 `buy_date` 字段，在 `on_trade()` 中记录买入日期，`on_bar()` 中判断 `can_sell`
- 涨跌停检测：根据 `stock_extra_info.json` 中的 `is_st` 字段和股票代码前缀（30/68 开头）动态计算涨跌停幅度
- 最小交易单位：`buy_stock()` / `sell_stock()` 内部使用 `int(volume // 100) * 100` 强制 100 股整数倍

**指标桥接层设计**
- vnpy 策略使用 `ArrayManager` 存储历史数据（numpy 数组）
- 技术指标函数使用 pandas DataFrame（便于向量化计算）
- `IndicatorCalculator` 负责转换：`ArrayManager` → `DataFrame` → 指标函数 → 结果字典

## 添加新策略

### 步骤 1：创建策略文件
在 `strategy/` 目录下创建新文件（如 `my_strategy.py`）：

```python
from vnpy.trader.object import BarData
from strategy.base_strategy import BaseStrategy

class MyStrategy(BaseStrategy):
    """我的策略"""
    author = "your_name"
    
    # 策略参数（用于参数优化）
    param1 = 10
    param2 = 20
    parameters = ["param1", "param2"]
    variables = []
    
    def execute_logic(self, bar: BarData, can_sell: bool,
                      at_upper_limit: bool, at_lower_limit: bool):
        """策略逻辑（每根 K 线调用一次）"""
        # 获取指标
        kdj = self.indicator.kdj()
        zx = self.indicator.zx_trend()
        
        # 买入逻辑
        if self.pos == 0 and not at_upper_limit:
            if kdj["J"] < 20:
                self.buy_stock(bar.close_price, 100)
        
        # 卖出逻辑
        if self.pos > 0 and can_sell and not at_lower_limit:
            if kdj["J"] > 80:
                self.sell_stock(bar.close_price, abs(self.pos))
```

### 步骤 2：注册策略
在 `main.py` 的 `cmd_backtest()` 和 `cmd_optimize()` 函数中添加：

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

## 添加新指标

### 步骤 1：在 indicator/indicators.py 中添加纯函数
```python
def calculate_my_indicator(df: pd.DataFrame, param: int = 10) -> pd.Series:
    """
    计算自定义指标
    :param df: 包含 close, high, low 等列的 DataFrame
    :param param: 参数
    :return: 指标值 Series
    """
    # 实现指标计算逻辑
    return df['close'].rolling(param).mean()
```

### 步骤 2：在 IndicatorCalculator 中添加桥接方法
```python
class IndicatorCalculator:
    def my_indicator(self, param: int = 10) -> float:
        """调用自定义指标"""
        df = self._to_dataframe()
        result = calculate_my_indicator(df, param)
        return result.iloc[-1]  # 返回最新值
```

### 步骤 3：在策略中使用
```python
def execute_logic(self, bar: BarData, can_sell: bool,
                  at_upper_limit: bool, at_lower_limit: bool):
    my_value = self.indicator.my_indicator(param=20)
    # 使用指标值进行交易决策
```

## 参数优化配置

在 `main.py` 的 `cmd_optimize()` 函数中修改优化参数：

```python
opt_setting = OptimizationSetting()
opt_setting.set_target("sharpe_ratio")  # 优化目标：sharpe_ratio / total_return / max_drawdown
opt_setting.add_parameter("kdj_j_buy", 5, 20, 5)    # 参数名, 最小值, 最大值, 步长
opt_setting.add_parameter("kdj_j_sell", 70, 90, 5)
```

## 注意事项

### 数据相关
- 首次使用必须运行 `python main.py data` 下载数据并导入 vnpy 数据库
- BaoStock 数据为前复权数据（`adjustflag="2"`）
- 数据增量更新：自动检测本地数据最新日期，只下载缺失部分
- 数据校验：导入时会校验 OHLC 合理性，跳过异常数据

### 回测相关
- 回测周期建议至少 6 个月，以获得统计意义
- 参数优化容易过拟合，优化后需在样本外数据验证
- 回测结果保存在 `reports/` 目录，文件名格式：`{strategy}_{symbol}.png`

### 策略开发
- 策略参数必须在 `parameters` 列表中声明，才能用于参数优化
- `execute_logic()` 中必须检查 `can_sell`（T+1）和涨跌停标志位
- 使用 `self.buy_stock()` / `self.sell_stock()` 而非 `self.buy()` / `self.sell()`（自动处理 100 股整数倍）
- 持仓通过 `self.pos` 获取（正数为多头，0 为空仓）

### 技术限制
- 当前仅支持日线回测（`interval="daily"`）
- 仅支持单股回测（不支持多股组合）
- 无测试框架（无 pytest 配置）
- 无 CI/CD 配置
- 无 Docker 部署配置
