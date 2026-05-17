"""
副图渲染器
可扩展的 Panel 系统，每个 PanelRenderer 子类负责一种技术指标的绘制
"""
from abc import ABC, abstractmethod
from typing import List

import pandas as pd
import numpy as np
import mplfinance as mpf


class PanelRenderer(ABC):
    """副图渲染器基类"""

    @abstractmethod
    def render(self, df: pd.DataFrame) -> List:
        """返回 mplfinance addplot 对象列表"""
        pass

    @abstractmethod
    def get_panel_id(self) -> int:
        """返回副图编号（0=主图，1/2/3...=副图）"""
        pass


class TrendLinePanel(PanelRenderer):
    """知行趋势线（叠加在主图上）"""

    def render(self, df):
        close = df["Close"]

        # 白线：EMA(EMA(C,10),10)
        ema1 = close.ewm(span=10, adjust=False).mean()
        white = ema1.ewm(span=10, adjust=False).mean()

        # 黄线：(MA14+MA28+MA57+MA114)/4
        ma14 = close.rolling(window=14, min_periods=1).mean()
        ma28 = close.rolling(window=28, min_periods=1).mean()
        ma57 = close.rolling(window=57, min_periods=1).mean()
        ma114 = close.rolling(window=114, min_periods=1).mean()
        yellow = (ma14 + ma28 + ma57 + ma114) / 4.0

        return [
            mpf.make_addplot(white, color='#FFFFFF', panel=0, width=1.2),
            mpf.make_addplot(yellow, color='#FFD700', panel=0, width=1.2),
        ]

    def get_panel_id(self):
        return 0


class KDJPanel(PanelRenderer):
    """KDJ 指标副图"""

    def render(self, df):
        n = 9
        high = df["High"]
        low = df["Low"]
        close = df["Close"]

        highest_high = high.rolling(window=n, min_periods=1).max()
        lowest_low = low.rolling(window=n, min_periods=1).min()
        rsv = (close - lowest_low) / (highest_high - lowest_low) * 100
        rsv = rsv.replace([np.inf, -np.inf], np.nan).fillna(50)

        k = pd.Series(index=rsv.index, dtype=float)
        d = pd.Series(index=rsv.index, dtype=float)
        k.iloc[0] = 50.0
        d.iloc[0] = 50.0
        for i in range(1, len(rsv)):
            k.iloc[i] = 2 / 3 * k.iloc[i - 1] + 1 / 3 * rsv.iloc[i]
            d.iloc[i] = 2 / 3 * d.iloc[i - 1] + 1 / 3 * k.iloc[i]
        j = 3 * k - 2 * d

        # panel=2 因为 panel=1 被 mplfinance 的 volume 占用
        return [
            mpf.make_addplot(k, color='#4A90E2', panel=2, width=0.8, ylabel='KDJ'),
            mpf.make_addplot(d, color='#F5A623', panel=2, width=0.8),
            mpf.make_addplot(j, color='#D0021B', panel=2, width=0.8),
        ]

    def get_panel_id(self):
        return 2
