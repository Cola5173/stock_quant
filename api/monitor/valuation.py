"""PE 分位数据拉取（沪深300、纳斯达克100）"""
import logging
from dataclasses import dataclass
from typing import Optional

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValuationInfo:
    index_name: str
    current_pe: Optional[float]
    percentile: Optional[float]
    is_overvalued: bool


def get_csi300_valuation(alert_percentile: float = 90) -> ValuationInfo:
    """获取沪深300 PE 分位数据（乐咕乐股）"""
    try:
        df = ak.index_value_hist_funddb(
            symbol="沪深300", indicator="市盈率"
        )
        if df.empty:
            logger.warning("沪深300 估值数据为空")
            return ValuationInfo("沪深300", None, None, False)

        df.columns = [c.strip() for c in df.columns]
        pe_col = "市盈率" if "市盈率" in df.columns else df.columns[-1]
        current_pe = float(df[pe_col].iloc[-1])
        percentile = (df[pe_col] < current_pe).sum() / len(df) * 100

        return ValuationInfo(
            index_name="沪深300",
            current_pe=round(current_pe, 2),
            percentile=round(percentile, 1),
            is_overvalued=percentile >= alert_percentile,
        )
    except Exception as e:
        logger.error(f"获取沪深300估值失败: {e}")
        return ValuationInfo("沪深300", None, None, False)


def get_nasdaq_valuation(alert_percentile: float = 90) -> ValuationInfo:
    """获取纳斯达克100 PE 分位数据"""
    try:
        df = ak.index_value_hist_funddb(
            symbol="纳斯达克100", indicator="市盈率"
        )
        if df.empty:
            logger.warning("纳斯达克100 估值数据为空")
            return ValuationInfo("纳斯达克100", None, None, False)

        df.columns = [c.strip() for c in df.columns]
        pe_col = "市盈率" if "市盈率" in df.columns else df.columns[-1]
        current_pe = float(df[pe_col].iloc[-1])
        percentile = (df[pe_col] < current_pe).sum() / len(df) * 100

        return ValuationInfo(
            index_name="纳斯达克100",
            current_pe=round(current_pe, 2),
            percentile=round(percentile, 1),
            is_overvalued=percentile >= alert_percentile,
        )
    except Exception as e:
        logger.error(f"获取纳斯达克100估值失败: {e}")
        return ValuationInfo("纳斯达克100", None, None, False)
