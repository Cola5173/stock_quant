"""
回测报告 + 可视化
基于 vnpy 回测结果生成统计报告和图表
"""
import os
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from vnpy_ctastrategy.backtesting import BacktestingEngine
from config import settings


class BacktestReporter:
    """回测报告生成器"""

    def __init__(self, engine: BacktestingEngine):
        self.engine = engine

    def summary(self) -> dict:
        """打印并返回回测统计指标"""
        stats = self.engine.calculate_statistics(output=True)
        return stats

    def plot(self, save_path: Optional[str] = None):
        """生成回测可视化图表"""
        df = self.engine.daily_df
        if df is None or df.empty:
            print("无回测数据，无法生成图表")
            return

        try:
            plt.style.use(settings.PLOT_STYLE)
        except OSError:
            pass

        fig, axes = plt.subplots(3, 1, figsize=(16, 12), sharex=True)

        # 1. 净值曲线
        if "balance" in df.columns:
            axes[0].plot(df.index, df["balance"], label="净值", color="steelblue")
            axes[0].set_title("净值曲线")
            axes[0].set_ylabel("资金 (元)")
            axes[0].legend()
            axes[0].grid(True)

        # 2. 回撤曲线
        if "drawdown" in df.columns:
            axes[1].fill_between(df.index, df["drawdown"], color="salmon", alpha=0.6)
            axes[1].set_title("回撤曲线")
            axes[1].set_ylabel("回撤 (%)")
            axes[1].legend(["回撤"])
            axes[1].grid(True)

        # 3. 每日盈亏
        if "net_pnl" in df.columns:
            colors = ["green" if x >= 0 else "red" for x in df["net_pnl"]]
            axes[2].bar(df.index, df["net_pnl"], color=colors, alpha=0.7)
            axes[2].set_title("每日盈亏")
            axes[2].set_ylabel("盈亏 (元)")
            axes[2].grid(True)

        plt.tight_layout()

        if save_path is None:
            os.makedirs(settings.REPORT_DIR, exist_ok=True)
            save_path = os.path.join(settings.REPORT_DIR, "backtest_report.png")
        else:
            os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)

        fig.savefig(save_path, dpi=150)
        plt.close(fig)
        print(f"图表已保存: {save_path}")
