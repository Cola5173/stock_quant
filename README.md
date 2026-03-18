# 股票选股系统

这是一个基于Python的股票选股系统，支持自定义策略进行选股。

## 功能特点

- 📊 支持多种数据源（Tushare、AKShare）
- 🎯 策略化设计，易于编写自定义选股策略
- 📈 内置示例策略（技术指标策略）
- 💾 支持结果导出（CSV、Excel）
- 🚀 支持进度显示和批量处理

## 安装依赖

```bash
pip install -r requirements.txt
```

## 使用方法

### 1. 使用AKShare数据源（推荐，免费）

```bash
python main.py --data-source akshare --max-stocks 50
```

### 2. 使用Tushare数据源（需要token）

```bash
python main.py --data-source tushare --tushare-token YOUR_TOKEN --max-stocks 50
```

### 3. 更多参数

```bash
python main.py \
    --data-source akshare \
    --max-stocks 100 \
    --min-score 10.0 \
    --output 选股结果.xlsx \
    --output-format excel
```

## 编写自定义策略

### 步骤1：创建策略文件

创建 `my_strategy.py` 文件：

```python
from strategy import Strategy
import pandas as pd

class MyCustomStrategy(Strategy):
    """我的自定义策略"""
    
    def __init__(self, data_fetcher):
        super().__init__("我的策略", data_fetcher)
        # 设置策略参数
        self.set_parameter('min_pe', 10)
        self.set_parameter('max_pe', 50)
    
    def calculate_score(self, stock_code: str, stock_data: pd.DataFrame) -> float:
        """计算股票得分"""
        if stock_data.empty:
            return 0.0
        
        # 在这里编写你的评分逻辑
        score = 0.0
        
        # 示例：基于涨幅评分
        if len(stock_data) >= 20:
            price_change = (stock_data.iloc[-1]['close'] - stock_data.iloc[-20]['close']) / stock_data.iloc[-20]['close']
            score = price_change * 100
        
        return score
    
    def filter_stock(self, stock_code: str, stock_data: pd.DataFrame) -> bool:
        """过滤股票"""
        if stock_data.empty:
            return False
        
        # 在这里编写你的筛选条件
        # 示例：只选择最近20日涨幅为正的股票
        if len(stock_data) >= 20:
            price_change = (stock_data.iloc[-1]['close'] - stock_data.iloc[-20]['close']) / stock_data.iloc[-20]['close']
            return price_change > 0
        
        return False
```

### 步骤2：在主程序中使用

修改 `main.py`：

```python
from strategy.my_strategy import MyCustomStrategy

# 替换示例策略
strategy = MyCustomStrategy(data_fetcher)
```

## 项目结构

```
stock/
├── data_fetcher.py      # 数据获取模块
├── strategy.py          # 策略基类和示例策略
├── stock_selector.py    # 选股执行模块
├── main.py             # 主程序入口
├── requirements.txt    # 依赖包
└── README.md          # 说明文档
```

## 策略接口说明

### Strategy 基类

所有策略都需要继承 `Strategy` 类并实现以下方法：

1. **calculate_score(stock_code, stock_data) -> float**
   - 计算股票得分
   - 返回分数（越高越好）

2. **filter_stock(stock_code, stock_data) -> bool**
   - 判断股票是否符合筛选条件
   - 返回 True 表示通过筛选

### 数据格式

`stock_data` 是一个 pandas DataFrame，包含以下列：
- `date`: 日期
- `open`: 开盘价
- `close`: 收盘价
- `high`: 最高价
- `low`: 最低价
- `volume`: 成交量
- `amount`: 成交额（如果有）

## 注意事项

1. **数据源选择**：
   - AKShare：免费，无需注册，但可能速度较慢
   - Tushare：需要注册获取token，数据更全面

2. **策略编写**：
   - 确保 `filter_stock` 方法先进行快速筛选，减少不必要的计算
   - `calculate_score` 方法可以更复杂，用于精细评分

3. **性能优化**：
   - 选股过程可能需要较长时间，建议先用小范围股票测试
   - 可以设置 `max_stocks` 限制返回数量

## 示例策略说明

内置的 `ExampleStrategy` 实现了以下筛选条件：
- 短期均线（20日）在长期均线（60日）之上
- 最近5日涨幅为正
- 成交量放大（最近5日平均成交量 > 最近20日平均成交量的1.2倍）

## 许可证

MIT License
