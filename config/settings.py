# @Author: cola5173
# @Time: 2025/12/7 02:31

DATA_DIR = "data"
RESOURCE_DIR = "resource"
STOCK_CODE_FILE = "resource/stock_code.csv"
STOCK_NAMES_FILE = "resource/stock_names.csv"
STRATEGY_DIR = "strategy"
REFERENCE_STOCK = "sh.000001"

# vnpy 数据库配置
VNPY_DB_PATH = "data/vnpy_db.sqlite"

# 回测默认参数
BACKTEST_CONFIG = {
    "capital": 100000,
    "rate": 0.001,
    "slippage": 0.01,
    "size": 1,
    "pricetick": 0.01,
    "interval": "daily",
}

# A 股费用明细（后续精细化时替换 rate 为自定义费用计算函数）
FEE_CONFIG = {
    "commission_rate": 0.0003,
    "stamp_tax_rate": 0.001,
    "transfer_fee_rate": 0.00001,
    "min_commission": 5.0,
}

# 可视化配置
REPORT_DIR = "reports"
PLOT_STYLE = "seaborn-v0_8-darkgrid"

# 输出目录
OUTPUT_DIR = "output"
CANDIDATES_DIR = "output/candidates"
CHARTS_DIR = "output/charts"
SCORES_DIR = "output/scores"
SIGNALS_DIR = "output/signals"
PORTFOLIO_DIR = "output/portfolio"

# 日志目录
LOG_DIR = "logs"

# 全市场股票列表缓存
STOCK_LIST_CACHE = "data/stock_list.csv"