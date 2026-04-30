"""
批量筛选引擎
对全市场股票进行策略条件扫描，找出候选股票
"""
import json
import logging
import os
from typing import List, Optional

import pandas as pd

from config import settings
from indicator.indicators import calculate_KDJ, calculate_zx_trend, calculate_amplitude
from model.kline_constants import KLineConstants
from utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)


class Scanner:
    """批量筛选引擎"""

    def __init__(self, strategy_name: str, stock_list: List[str]):
        """
        :param strategy_name: 策略名称（如 'b1'）
        :param stock_list: 股票代码列表（格式：sh.600000 或纯数字 600000）
        """
        self.strategy_name = strategy_name
        self.stock_list = stock_list
        self._extra_info = self._load_extra_info()

    def _load_extra_info(self) -> dict:
        path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
        return {}

    def scan(self, date: str) -> List[dict]:
        """
        扫描全市场，返回候选股票列表
        :param date: 扫描日期（YYYY-MM-DD）
        :return: 候选股票列表
        """
        from tqdm import tqdm

        candidates = []
        skipped = 0

        for stock_code in tqdm(self.stock_list, desc="扫描股票"):
            try:
                symbol = _normalize_stock_code(stock_code)
                result = self._check_stock(symbol, date)
                if result:
                    candidates.append(result)
            except Exception as e:
                logger.debug(f"扫描 {stock_code} 失败: {e}")
                skipped += 1
                continue

        logger.info(f"扫描完成: {len(candidates)} 只候选 / {len(self.stock_list)} 只总计 / {skipped} 只跳过")
        return candidates

    def _check_stock(self, symbol: str, date: str) -> Optional[dict]:
        """
        检查单只股票是否符合策略买入条件
        :return: 匹配则返回候选信息字典，否则返回 None
        """
        df = self._load_stock_data(symbol, date)
        if df is None or len(df) < 30:
            return None

        # 计算指标
        try:
            kdj = calculate_KDJ(df)
            zx = calculate_zx_trend(df)
            amp = calculate_amplitude(df)
        except Exception:
            return None

        # 涨跌停检测
        if len(df) < 2:
            return None
        prev_close = df[KLineConstants.CLOSE].iloc[-2]
        curr_close = df[KLineConstants.CLOSE].iloc[-1]
        limit_rate = self._get_limit_rate(symbol)
        pct = (curr_close - prev_close) / prev_close if prev_close > 0 else 0
        at_upper_limit = pct >= limit_rate - 0.001

        # 应用 B1 策略买入条件
        matched = self._apply_b1_filter(kdj, zx, curr_close, at_upper_limit)

        if not matched:
            return None

        return {
            "symbol": symbol,
            "name": self._get_stock_name(symbol),
            "match_date": date,
            "close": curr_close,
            "indicators": {
                "kdj_j": kdj["J"],
                "kdj_k": kdj["K"],
                "kdj_d": kdj["D"],
                "zx_white": zx["zx_trend_white"],
                "zx_yellow": zx["zx_trend_yellow"],
                "amplitude": amp["amplitude"],
            }
        }

    def _apply_b1_filter(self, kdj: dict, zx: dict, close: float, at_upper_limit: bool) -> bool:
        """B1 策略买入条件"""
        return (
            not at_upper_limit
            and kdj["J"] < 13
            and zx["zx_trend_white"] > zx["zx_trend_yellow"]
            and close > zx["zx_trend_yellow"] * 0.99
        )

    def _load_stock_data(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        """从 CSV 文件加载股票数据（最近 200 天）"""
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
            df = df.sort_values(KLineConstants.DATE).tail(200).reset_index(drop=True)

            if df.empty:
                return None
            return df
        except Exception:
            return None

    def _get_limit_rate(self, symbol: str) -> float:
        info = self._extra_info.get(symbol, {})
        if info.get("is_st", False):
            return 0.05
        if symbol.startswith("30") or symbol.startswith("68"):
            return 0.20
        return 0.10

    def _get_stock_name(self, symbol: str) -> str:
        """尝试从 CSV 数据中获取股票名称"""
        return symbol

    def save_candidates(self, candidates: List[dict], date: str) -> str:
        """
        保存候选股票到 JSON 文件
        :return: 输出文件路径
        """
        os.makedirs(settings.CANDIDATES_DIR, exist_ok=True)
        date_str = date.replace("-", "")
        output_path = os.path.join(settings.CANDIDATES_DIR, f"candidates_{date_str}.json")

        result = {
            "scan_date": date,
            "strategy": self.strategy_name,
            "total_scanned": len(self.stock_list),
            "candidates_count": len(candidates),
            "candidates": candidates,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"候选股票已保存到 {output_path}")
        return output_path
