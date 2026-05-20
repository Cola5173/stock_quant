"""B2 Small 策略：B2 + 小资金过滤（仅主板 + 价格上限）"""
from api.strategy.b1_small import B1SmallStrategy
from api.strategy.b2 import B2Strategy


class B2SmallStrategy(B2Strategy, B1SmallStrategy):
    """B2 小资金版：继承 B2 选股 + B1Small 资金管理（止损/T+5/主板过滤）"""
    author = "stock_quant"
