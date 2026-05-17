"""
K线图生成器
支持可扩展副图系统，为 LLM 打分提供图形输入
"""
import logging
import os
from typing import List, Optional

import pandas as pd
import mplfinance as mpf

from api.config import settings
from api.schemas.kline_constants import KLineConstants
from api.visualizer.panels import PanelRenderer, TrendLinePanel, KDJPanel

logger = logging.getLogger(__name__)

MIN_BARS_FOR_CHART = 20
DEFAULT_BARS_COUNT = 60


class ChartGenerator:
    """K线图生成器（支持可扩展副图）"""

    def __init__(self, panels: List[PanelRenderer] = None):
        """
        :param panels: 副图渲染器列表，默认 [TrendLinePanel, KDJPanel]
        """
        self.panels = panels if panels is not None else [TrendLinePanel(), KDJPanel()]

    def generate(self, symbol: str, date: str, output_path: str,
                 bars_count: int = DEFAULT_BARS_COUNT) -> Optional[str]:
        """
        生成K线图
        :param symbol: 股票代码（纯数字，如 600000）
        :param date: 截止日期（YYYY-MM-DD）
        :param output_path: 输出文件路径
        :param bars_count: 显示的K线数量
        :return: 输出文件路径，失败返回 None
        """
        df = self._load_data(symbol, date, bars_count)
        if df is None:
            return None

        if len(df) < MIN_BARS_FOR_CHART:
            logger.warning(f"{symbol} 数据不足 {MIN_BARS_FOR_CHART} 天，跳过")
            return None

        try:
            all_plots = []
            for panel in self.panels:
                try:
                    plots = panel.render(df)
                    all_plots.extend(plots)
                except Exception as e:
                    logger.warning(f"{symbol} 渲染 {panel.__class__.__name__} 失败: {e}")
                    continue

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            mpf.plot(
                df,
                type='candle',
                addplot=all_plots if all_plots else None,
                volume=True,
                style='charles',
                figsize=(12, 8),
                title=f"{symbol} ({len(df)}天)",
                savefig=dict(fname=output_path, dpi=100, bbox_inches='tight'),
            )

            logger.info(f"K线图已生成: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"生成 {symbol} K线图失败: {e}")
            return None

    def generate_batch(self, candidates: List[dict], date: str) -> List[str]:
        """
        批量生成K线图
        :param candidates: 候选股票列表
        :param date: 截止日期
        :return: 成功生成的图片路径列表
        """
        from tqdm import tqdm

        os.makedirs(settings.CHARTS_DIR, exist_ok=True)
        date_str = date.replace("-", "")
        chart_paths = []

        for candidate in tqdm(candidates, desc="生成K线图"):
            symbol = candidate["symbol"]
            output_path = os.path.join(settings.CHARTS_DIR, f"{symbol}_{date_str}.png")
            result = self.generate(symbol, date, output_path)
            if result:
                chart_paths.append(result)

        logger.info(f"K线图生成完成: {len(chart_paths)}/{len(candidates)}")
        return chart_paths

    def _load_data(self, symbol: str, date: str, bars_count: int) -> Optional[pd.DataFrame]:
        """从 CSV 加载数据并转换为 mplfinance 所需格式"""
        csv_path = os.path.join(settings.DATA_DIR, f"{symbol}.csv")
        if not os.path.exists(csv_path):
            return None

        try:
            df = pd.read_csv(csv_path)
            if df.empty:
                return None

            for col in [KLineConstants.OPEN, KLineConstants.HIGH, KLineConstants.LOW,
                        KLineConstants.CLOSE, KLineConstants.VOLUME]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")

            df[KLineConstants.DATE] = pd.to_datetime(df[KLineConstants.DATE])
            df = df[df[KLineConstants.DATE] <= pd.to_datetime(date)]
            df = df.sort_values(KLineConstants.DATE).tail(bars_count).reset_index(drop=True)

            if df.empty:
                return None

            # mplfinance 要求 DatetimeIndex + OHLCV 列名
            df = df.rename(columns={
                KLineConstants.DATE: "Date",
                KLineConstants.OPEN: "Open",
                KLineConstants.HIGH: "High",
                KLineConstants.LOW: "Low",
                KLineConstants.CLOSE: "Close",
                KLineConstants.VOLUME: "Volume",
            })
            df = df.set_index("Date")

            # 丢弃 NaN 行
            df = df.dropna(subset=["Open", "High", "Low", "Close"])

            return df if not df.empty else None

        except Exception as e:
            logger.error(f"加载 {symbol} 数据失败: {e}")
            return None
