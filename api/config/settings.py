# @Author: cola5173
# @Time: 2025/12/7 02:31
import os as _os

# 项目根目录（settings.py 在 api/config/，向上三级到项目根）
PROJECT_ROOT = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))


def _abs(rel: str) -> str:
    """将相对路径解析为基于项目根的绝对路径"""
    return _os.path.join(PROJECT_ROOT, rel)


# ====== API 服务（可被环境变量覆盖） ======
API_HOST = _os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(_os.getenv("API_PORT", "7088"))


DATA_DIR = _abs("data")
RESOURCE_DIR = _abs("api/resource")
STOCK_CODE_FILE = _abs("api/resource/stock_code.csv")
STOCK_NAMES_FILE = _abs("api/resource/stock_names.csv")
STRATEGY_DIR = _abs("strategy")
REFERENCE_STOCK = "sh.000001"

# vnpy 数据库配置
VNPY_DB_PATH = _abs("data/vnpy_db.sqlite")

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
REPORT_DIR = _abs("reports")
PLOT_STYLE = "seaborn-v0_8-darkgrid"

# 输出目录
OUTPUT_DIR = _abs("output")
CANDIDATES_DIR = _abs("output/candidates")
CHARTS_DIR = _abs("output/charts")
SCORES_DIR = _abs("output/scores")
SIGNALS_DIR = _abs("output/signals")
PORTFOLIO_DIR = _abs("output/portfolio")

# 日志目录
LOG_DIR = _abs("logs")

# 全市场股票列表缓存
STOCK_LIST_CACHE = _abs("data/stock_list.csv")

# ====== Advisor 配置 ======
POSITIONS_FILE = _abs("data/positions.json")
CLOSED_TRADES_FILE = _abs("data/closed_trades.json")
DECISIONS_DIR = _abs("output/decisions")

EMAIL_CONFIG = {
    "host": "smtp.qq.com",
    "port": 465,
    "use_ssl": True,
    "user": _os.getenv("QQ_EMAIL_USER", ""),
    "password": _os.getenv("QQ_EMAIL_PASS", ""),
    "to": _os.getenv("QQ_EMAIL_TO", ""),
    "sender_name": "Stock Quant Daily",
}

ADVISOR_CONFIG = {
    "max_slots_strong": 2,
    "max_slots_weak": 1,
    "single_position_pct_strong": 0.50,
    "single_position_pct_weak": 0.40,
    "cooldown_loss_streak": 2,
    "cooldown_offset": 15,
    "retry_times": 3,
    "retry_interval_sec": 60,
}