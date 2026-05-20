"""
B2 策略：B1 的次日确认买入（"B2 确认 B1，B3 确认 B2"）

核心逻辑（与 B1 的差异在选股端）：
- T-1（昨日）该股票是 B1 命中票
- T 日（今日）出现「B2 确认 K」：放量中长阳 + 收盘 > 开盘 > 昨收 + 偏光头
- 形态分类（首期实现"多门重炮"）：
  - T 日（"右门"）往前 lookback 日内有另一根放量中阳（"左门"）
  - 两门之间至少 N 根阴线
  - 两门成交量都 ≥ 中间阴线最大成交量（"压住中间"）

持仓 / 卖出逻辑完全继承 B1Strategy（不做改动）。
策略类本身只是命名标识，选股逻辑在 tests/scan_b2_full.py。
"""
from api.strategy.b1 import B1Strategy


class B2Strategy(B1Strategy):
    """B2 = B1 + 次日放量阳确认 + 形态识别"""

    author = "stock_quant"

    # B2 选股参数（仅供 scan_b2_full 读取，不影响 B1 主逻辑）
    b2_body_min_pct = 3.0           # T 日中长阳最小实体涨幅
    b2_vol_ratio_min = 1.5          # T 日量比相对前 5 日均量
    b2_upper_shadow_max = 0.3       # T 日上影线 / 实体 ≤ 此值（光头特征）

    # 多门重炮参数
    duomen_lookback = 20            # T 日往前找"左门"的窗口
    duomen_door_body_min = 3.0      # 左门最小实体涨幅
    duomen_door_vol_ratio = 1.5     # 左门量比阈值
    duomen_min_bears = 3            # 中间至少阴线数
    duomen_strict_press = True      # 两门量都 ≥ 中间阴线最大量

    parameters = B1Strategy.parameters + [
        "b2_body_min_pct", "b2_vol_ratio_min", "b2_upper_shadow_max",
        "duomen_lookback", "duomen_door_body_min",
        "duomen_door_vol_ratio", "duomen_min_bears", "duomen_strict_press",
    ]
