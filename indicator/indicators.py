"""
技术指标计算模块
提供各种技术指标的计算函数
"""
import pandas as pd
import numpy as np
from api.schemas.kline_constants import KLineConstants


def calculate_KDJ(df: pd.DataFrame) -> dict:
    """
    计算KDJ指标，返回最后一个交易日的KDJ值
    :param df: 包含 high、low、close 列的DataFrame
    :return: 字典，包含最后一个交易日的 RSV、K、D、J 值，例如 {'RSV': 50.0, 'K': 50.0, 'D': 50.0, 'J': 50.0}
    """
    n = 9
    m1 = 3
    m2 = 3

    # 如果第一个参数是 DataFrame，从中提取 high、low、close
    if isinstance(df, pd.DataFrame):
        high = df[KLineConstants.HIGH]
        low = df[KLineConstants.LOW]
        close = df[KLineConstants.CLOSE]
    else:
        raise ValueError("df 必须是 DataFrame")

    # 计算N日最高价和最低价
    highest_high = high.rolling(window=n, min_periods=1).max()
    lowest_low = low.rolling(window=n, min_periods=1).min()

    # 计算RSV
    rsv = (close - lowest_low) / (highest_high - lowest_low) * 100

    # 处理分母为0的情况（最高价等于最低价）
    rsv = rsv.replace([np.inf, -np.inf], np.nan)
    rsv = rsv.fillna(50)  # 当最高价等于最低价时，RSV设为50

    # 初始化K和D值（初始值为50）
    k = pd.Series(index=rsv.index, dtype=float)
    d = pd.Series(index=rsv.index, dtype=float)

    # 计算K值：EMA平滑RSV
    # K值 = (m1-1)/m1 * 前一日K值 + 1/m1 * 当日RSV
    k[0] = 50.0  # 初始K值
    for i in range(1, len(rsv)):
        k[i] = (m1 - 1) / m1 * k[i - 1] + 1 / m1 * rsv.iloc[i]

    # 计算D值：EMA平滑K值
    # D值 = (m2-1)/m2 * 前一日D值 + 1/m2 * 当日K值
    d[0] = 50.0  # 初始D值
    for i in range(1, len(k)):
        d[i] = (m2 - 1) / m2 * d[i - 1] + 1 / m2 * k.iloc[i]

    # 计算J值：J = 3*K - 2*D
    j = 3 * k - 2 * d

    # 只返回最后一个交易日的KDJ值，四舍五入到小数点后两位
    return {
        'RSV': round(rsv.iloc[-1], 2),
        'K': round(k.iloc[-1], 2),
        'D': round(d.iloc[-1], 2),
        'J': round(j.iloc[-1], 2)
    }


def calculate_zx_trend(df: pd.DataFrame) -> dict:
    """
    计算知行相关指标，返回最后一个交易日的所有知行指标值
    
    包含两个指标：
    1. 知行多空线 = (MA(CLOSE,M1) + MA(CLOSE,M2) + MA(CLOSE,M3) + MA(CLOSE,M4)) / 4
    2. 知行短期趋势线 = EMA(EMA(C, period), period)
    
    其中：
    - MA(CLOSE,M1-M4) 是收盘价的M1-M4日简单移动平均
    - EMA(C, period) 是收盘价的period日指数移动平均
    - EMA(EMA(C, period), period) 是对第一次EMA结果再次计算period日指数移动平均
    
    :param df: 包含 close 列的DataFrame
    :return: 字典，包含最后一个交易日的所有知行指标值
    """

    if KLineConstants.CLOSE not in df.columns:
        raise ValueError(f"DataFrame 必须包含 {KLineConstants.CLOSE} 列")
    if KLineConstants.LOW not in df.columns:
        raise ValueError(f"DataFrame 必须包含 {KLineConstants.LOW} 列")

    close = df[KLineConstants.CLOSE]
    low = df[KLineConstants.LOW]

    # ================================ 知行指标 - 短期 ================================
    # 短期:100*(C-LLV(L,N1))/(HHV(C,N1)-LLV(L,N1))
    # N1 = 3
    # LLV(L,N1) 是 N1 日内最低价的最低值
    # HHV(C,N1) 是 N1 日内收盘价的最高值
    llv_l = low.rolling(window=3, min_periods=1).min()  # LLV(L,3)
    hhv_c = close.rolling(window=3, min_periods=1).max()  # HHV(C,3)
    zx_short = 100 * (close - llv_l) / (hhv_c - llv_l)
    
    # 处理分母为0的情况
    zx_short = zx_short.replace([np.inf, -np.inf], np.nan)
    zx_short = zx_short.fillna(50)  # 当最高价等于最低价时，设为50

    # ================================ 知行指标 - 长期 ================================
    # 长期:100*(C-LLV(L,N2))/(HHV(C,N2)-LLV(L,N2))
    # N2 = 21
    # LLV(L,N2) 是 N2 日内最低价的最低值
    # HHV(C,N2) 是 N2 日内收盘价的最高值
    llv_l_long = low.rolling(window=21, min_periods=1).min()  # LLV(L,21)
    hhv_c_long = close.rolling(window=21, min_periods=1).max()  # HHV(C,21)
    zx_long = 100 * (close - llv_l_long) / (hhv_c_long - llv_l_long)
    
    # 处理分母为0的情况
    zx_long = zx_long.replace([np.inf, -np.inf], np.nan)
    zx_long = zx_long.fillna(50)  # 当最高价等于最低价时，设为50

    # ================================ 知行指标 - 趋势白 ================================
    # EMA(EMA(C,10),10)
    ema1 = close.ewm(span=10, adjust=False).mean()
    zx_trend_white = ema1.ewm(span=10, adjust=False).mean()

    # ================================ 知行指标 - 大哥黄 ================================
    # (MA(CLOSE,M1)+MA(CLOSE,M2)+MA(CLOSE,M3)+MA(CLOSE,M4))/4;
    ma1 = close.rolling(window=14, min_periods=1).mean()  # MA(CLOSE,M1)
    ma2 = close.rolling(window=28, min_periods=1).mean()  # MA(CLOSE,M2)
    ma3 = close.rolling(window=57, min_periods=1).mean()  # MA(CLOSE,M3)
    ma4 = close.rolling(window=114, min_periods=1).mean()  # MA(CLOSE,M4)
    zx_trend_yellow = (ma1 + ma2 + ma3 + ma4) / 4.0

    # ================================ 知行指标 - BBI ================================
    # BBI:(MA(CLOSE,N1)+MA(CLOSE,N2)+MA(CLOSE,N3)+MA(CLOSE,N4))/4;
    bbi_ma1 = close.rolling(window=3, min_periods=1).mean()  # MA(CLOSE,M1)
    bbi_ma2 = close.rolling(window=6, min_periods=1).mean()  # MA(CLOSE,M2)
    bbi_ma3 = close.rolling(window=12, min_periods=1).mean()  # MA(CLOSE,M3)
    bbi_ma4 = close.rolling(window=24, min_periods=1).mean()  # MA(CLOSE,M4)
    bbi = (bbi_ma1 + bbi_ma2 + bbi_ma3 + bbi_ma4) / 4.0

    # ================================ 知行指标 - 滴滴战法 ================================
    # 今天的收盘价是否比昨日的最低价高
    dd = close.iloc[-1] > df[KLineConstants.LOW].iloc[-2]

    # 返回最后一个交易日的所有值，四舍五入到小数点后两位
    return {
        'zx_short': round(zx_short.iloc[-1], 2),
        'zx_long': round(zx_long.iloc[-1], 2),
        'zx_trend_yellow': round(zx_trend_yellow.iloc[-1], 2),
        'zx_trend_white': round(zx_trend_white.iloc[-1], 2),
        'bbi': round(bbi.iloc[-1], 2),
        'dd': dd
    }


def calculate_amplitude(df: pd.DataFrame) -> dict:
    """
    振幅指标
    :param df: 包含 high、low、close 列的DataFrame
    :return: 字典，包含最后一个交易日的振幅值，例如 {'amplitude': 50.0}
    振幅区间 := IF(CODELIKE('68') OR CODELIKE('30') OR CODELIKE('4') OR CODELIKE('8') OR CODELIKE('9') OR EXIST(C/REF(C,1)>1.15,200), 8, 5);
    """
    if KLineConstants.HIGH not in df.columns:
        raise ValueError(f"DataFrame 必须包含 {KLineConstants.HIGH} 列")
    if KLineConstants.LOW not in df.columns:
        raise ValueError(f"DataFrame 必须包含 {KLineConstants.LOW} 列")
    if KLineConstants.CLOSE not in df.columns:
        raise ValueError(f"DataFrame 必须包含 {KLineConstants.CLOSE} 列")
    high = df[KLineConstants.HIGH]
    low = df[KLineConstants.LOW]
    close = df[KLineConstants.CLOSE]
    amplitude = (high - low) / low * 100
    return {'amplitude': round(amplitude.iloc[-1], 2)}


class IndicatorCalculator:
    """
    桥接层：将 vnpy ArrayManager 的 numpy 数组转为 DataFrame，
    复用现有 pandas 向量化指标计算函数
    """

    def __init__(self, am):
        self.am = am
        self._df = self._am_to_dataframe()

    def _am_to_dataframe(self) -> pd.DataFrame:
        return pd.DataFrame({
            KLineConstants.OPEN: self.am.open_array,
            KLineConstants.HIGH: self.am.high_array,
            KLineConstants.LOW: self.am.low_array,
            KLineConstants.CLOSE: self.am.close_array,
            KLineConstants.VOLUME: self.am.volume_array,
        })

    def kdj(self, n=9, m1=3, m2=3) -> dict:
        return calculate_KDJ(self._df)

    def zx_trend(self) -> dict:
        result = calculate_zx_trend(self._df)
        return {
            "zx_short": result["zx_short"],
            "zx_long": result["zx_long"],
            "white": result["zx_trend_white"],
            "yellow": result["zx_trend_yellow"],
            "bbi": result["bbi"],
            "didi": result["dd"],
        }

    def amplitude(self) -> float:
        result = calculate_amplitude(self._df)
        return result["amplitude"]
