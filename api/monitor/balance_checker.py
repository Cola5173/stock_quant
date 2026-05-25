"""核心仓比例偏离计算"""
import json
import os
from dataclasses import dataclass
from typing import Dict, List

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")


@dataclass
class DeviationItem:
    code: str
    name: str
    amount: float
    current_pct: float
    target_pct: float
    deviation: float
    need_rebalance: bool


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def check_balance(config: dict = None) -> List[DeviationItem]:
    if config is None:
        config = load_config()

    holdings = config["holdings"]
    targets = config["target_allocation"]
    threshold = config.get("alert_threshold", 0.05)

    total = sum(h["amount"] for h in holdings.values())
    if total <= 0:
        return []

    results = []
    for code, info in holdings.items():
        current_pct = info["amount"] / total
        target_pct = targets.get(code, 0)
        deviation = current_pct - target_pct
        results.append(DeviationItem(
            code=code,
            name=info["name"],
            amount=info["amount"],
            current_pct=current_pct,
            target_pct=target_pct,
            deviation=deviation,
            need_rebalance=abs(deviation) > threshold,
        ))
    return results
