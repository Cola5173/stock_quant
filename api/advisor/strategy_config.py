"""策略参数注册表：模拟盘决策引擎根据 strategy_key 读取对应配置"""

STRATEGY_CONFIGS = {
    "b1_small": {
        "label": "B1 Small",
        "description": "B1 小资金版：仅主板 + 严格止损 + T+5 时间止损",
        "scan_module": "api.advisor.scan_b1_small",
        "hold_days": 5,
        "min_gain_pct": 2.5,
        "weak_stop_loss_pct": 3.0,
        "strong_stop_loss_pct": 5.0,
        "max_slots_strong": 2,
        "max_slots_weak": 1,
        "single_position_pct_strong": 0.50,
        "single_position_pct_weak": 0.40,
    },
    "b2_small": {
        "label": "B2 Small",
        "description": "B2 小资金版：T-1 是 B1 + T 日放量阳确认 + 多门重炮形态识别",
        "scan_module": "api.advisor.scan_b1_small",  # 沿用 B1 卖出/止损逻辑
        "hold_days": 5,
        "min_gain_pct": 2.5,
        "weak_stop_loss_pct": 3.0,
        "strong_stop_loss_pct": 5.0,
        "max_slots_strong": 2,
        "max_slots_weak": 1,
        "single_position_pct_strong": 0.50,
        "single_position_pct_weak": 0.40,
    },
}


def get_config(strategy_key: str) -> dict:
    if strategy_key not in STRATEGY_CONFIGS:
        raise ValueError(f"未知策略: {strategy_key}，可选: {list(STRATEGY_CONFIGS.keys())}")
    return STRATEGY_CONFIGS[strategy_key]
