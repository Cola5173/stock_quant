# 环节 2：筛选 + K 线图生成

> 上游依赖：环节 1（数据拉取）
> 下游消费：环节 3（LLM 打分）
> 输入：`data/vnpy_db.sqlite`、`data/stock_extra_info.json`
> 输出：`output/candidates/candidates_{date}.json`、`output/charts/{symbol}_{date}.png`

## 1. Scanner 批量筛选模块

### 1.1 职责

对全市场股票进行批量筛选，找出符合策略条件的候选股票。

### 1.2 核心类

```python
class Scanner:
    """批量筛选引擎"""

    def __init__(self, strategy_class, stock_list: List[str]):
        self.strategy_class = strategy_class
        self.stock_list = stock_list

    def scan(self, date: str) -> List[dict]:
        """扫描全市场，返回候选股票列表"""
        candidates = []
        for stock_code in self.stock_list:
            if self._check_stock(stock_code, date):
                candidates.append({
                    "symbol": stock_code,
                    "match_date": date,
                    "indicators": self._get_indicators(stock_code)
                })
        return candidates

    def _check_stock(self, stock_code: str, date: str) -> bool:
        """检查单只股票是否符合策略买入条件"""
        # 1. 从 vnpy 数据库加载最近 200 天数据
        # 2. 计算技术指标（KDJ、知行趋势等）
        # 3. 应用策略买入条件
        # 4. 返回是否匹配
        pass

    def _get_indicators(self, stock_code: str) -> dict:
        """获取股票当前指标值"""
        pass
```

### 1.3 筛选条件

复用现有策略的买入逻辑。以 B1 策略为例：
- KDJ 的 J 值 < 13（低位）
- 趋势白线在黄线上方
- 收盘价在黄线 -1% 之上
- 未涨停

### 1.4 性能优化

- MVP 阶段：单进程串行扫描，5000 只股票约 15-20 分钟
- 优化阶段：使用 `multiprocessing.Pool` 多进程并行，可缩短至 5-8 分钟

### 1.5 输出格式

```json
// output/candidates/candidates_20260429.json
{
  "scan_date": "2026-04-29",
  "strategy": "b1",
  "total_scanned": 5000,
  "candidates_count": 87,
  "candidates": [
    {
      "symbol": "600000",
      "name": "浦发银行",
      "close": 8.52,
      "indicators": {
        "kdj_j": 11.23,
        "zx_white": 8.45,
        "zx_yellow": 8.32,
        "amplitude": 3.2
      }
    }
  ]
}
```

## 2. Visualizer K 线图生成模块

### 2.1 职责

为候选股票生成带技术指标的 K 线图，供 LLM 分析。

### 2.2 技术选型

mplfinance（matplotlib 金融图表扩展）

### 2.3 可扩展副图系统

```python
from abc import ABC, abstractmethod

class PanelRenderer(ABC):
    """副图渲染器基类"""

    @abstractmethod
    def render(self, df: pd.DataFrame) -> List[mpf.make_addplot]:
        """返回 mplfinance addplot 对象列表"""
        pass

    @abstractmethod
    def get_panel_id(self) -> int:
        """返回副图编号（0=主图，1/2/3...=副图）"""
        pass


class TrendLinePanel(PanelRenderer):
    """知行趋势线（叠加在主图上）"""

    def render(self, df):
        zx = calculate_zx_trend(df)
        return [
            mpf.make_addplot(zx['white'], color='white', panel=0),
            mpf.make_addplot(zx['yellow'], color='yellow', panel=0)
        ]

    def get_panel_id(self):
        return 0


class KDJPanel(PanelRenderer):
    """KDJ 指标副图"""

    def render(self, df):
        kdj = calculate_KDJ(df)
        return [
            mpf.make_addplot(kdj['K'], color='blue', panel=1),
            mpf.make_addplot(kdj['D'], color='orange', panel=1),
            mpf.make_addplot(kdj['J'], color='red', panel=1)
        ]

    def get_panel_id(self):
        return 1
```

### 2.4 ChartGenerator 核心类

```python
class ChartGenerator:
    """K线图生成器（支持可扩展副图）"""

    def __init__(self, panels: List[PanelRenderer] = None):
        self.panels = panels or [TrendLinePanel(), KDJPanel()]

    def generate(self, symbol, start_date, end_date, output_path):
        """生成K线图"""
        df = self._load_data(symbol, start_date, end_date)

        all_plots = []
        for panel in self.panels:
            all_plots.extend(panel.render(df))

        mpf.plot(df, type='candle', addplot=all_plots,
                 volume=True, savefig=output_path,
                 style='charles', figsize=(12, 8))
```

### 2.5 图表布局

- Panel 0（主图）：K 线 + 白线（短期趋势）+ 黄线（长期趋势）
- Panel 1（副图 1）：KDJ 指标（K 线、D 线、J 线）
- Panel 2（副图 2）：成交量柱状图
- 后续可扩展：MACD、RSI、布林带等

### 2.6 扩展新副图的步骤

1. 在 `indicator/indicators.py` 中实现新指标计算函数
2. 在 `visualizer/panels.py` 中创建新的 `PanelRenderer` 子类
3. 在配置中启用新副图或在代码中传入新 Panel 实例

### 2.7 输出

- 文件路径：`output/charts/{symbol}_{date}.png`
- 图片尺寸：1200x800 像素
- 时间范围：最近 60 个交易日
- 数据不足处理：如果不足 60 天，使用实际可用天数（最少 20 天）；少于 20 天则跳过该股票

## 3. CLI 命令

```bash
# 全市场扫描（自动生成 K 线图）
python main.py scan --strategy b1 --date 2026-04-29
# 输出: output/candidates/candidates_20260429.json
# 输出: output/charts/*.png
```
