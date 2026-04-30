"""
组合回测报告生成
输出统计指标和可视化图表
"""
import json
import logging
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from config import settings

logger = logging.getLogger(__name__)


class PortfolioReporter:
    """组合回测报告"""

    def __init__(self, result: dict):
        self.result = result

    def summary(self):
        """打印统计摘要"""
        stats = self.result.get("statistics", {})
        period = self.result.get("period", {})

        print(f"回测区间: {period.get('start')} ~ {period.get('end')}")
        print(f"初始资金: {stats.get('initial_capital', 0):,.0f}")
        print(f"最终资产: {stats.get('final_value', 0):,.2f}")
        print(f"总收益率: {stats.get('total_return', 0):.2f}%")
        print(f"年化收益: {stats.get('annual_return', 0):.2f}%")
        print(f"最大回撤: {stats.get('max_drawdown', 0):.2f}%")
        print(f"夏普比率: {stats.get('sharpe_ratio', 0):.2f}")
        print(f"胜率:     {stats.get('win_rate', 0):.2f}%")
        print(f"总交易数: {stats.get('total_trades', 0)}")

    def plot(self, save_path: str = None):
        """生成净值曲线图"""
        daily_values = self.result.get("daily_values", [])
        if not daily_values:
            logger.warning("无每日净值数据，跳过绘图")
            return

        dates = [v["date"] for v in daily_values]
        values = [v["total_value"] for v in daily_values]

        fig, axes = plt.subplots(2, 1, figsize=(12, 8), gridspec_kw={'height_ratios': [3, 1]})

        # 净值曲线
        axes[0].plot(dates, values, color='#4A90E2', linewidth=1.2)
        axes[0].axhline(y=self.result["statistics"]["initial_capital"],
                        color='gray', linestyle='--', alpha=0.5)
        axes[0].set_title('Portfolio Net Value')
        axes[0].set_ylabel('Value (CNY)')
        axes[0].tick_params(axis='x', rotation=45)
        step = max(1, len(dates) // 10)
        axes[0].set_xticks(range(0, len(dates), step))

        # 回撤曲线
        import pandas as pd
        import numpy as np
        vs = pd.Series(values)
        peak = vs.cummax()
        drawdown = (vs - peak) / peak * 100
        axes[1].fill_between(range(len(drawdown)), drawdown, color='#D0021B', alpha=0.3)
        axes[1].plot(range(len(drawdown)), drawdown, color='#D0021B', linewidth=0.8)
        axes[1].set_title('Drawdown')
        axes[1].set_ylabel('Drawdown (%)')
        axes[1].set_xticks(range(0, len(dates), step))
        axes[1].set_xticklabels([dates[i] for i in range(0, len(dates), step)], rotation=45)

        plt.tight_layout()

        if save_path:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            plt.savefig(save_path, dpi=100, bbox_inches='tight')
            logger.info(f"回测图表已保存到 {save_path}")
        plt.close()

    def save_json(self, date_range: str) -> str:
        """保存回测结果到 JSON"""
        os.makedirs(settings.PORTFOLIO_DIR, exist_ok=True)
        output_path = os.path.join(settings.PORTFOLIO_DIR, f"backtest_{date_range}.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.result, f, ensure_ascii=False, indent=2)

        logger.info(f"回测结果已保存到 {output_path}")
        return output_path
