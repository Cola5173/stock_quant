"""
批量筛选引擎
对全市场股票进行策略条件扫描，找出候选股票
评分逻辑复用 tests/scan_b1_full.check_one（与 tests/portfolio_b1_small.py 一致）
"""
import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Optional

from api.config import settings
from api.utils.utils import _normalize_stock_code

logger = logging.getLogger(__name__)

# 确保 tests/ 可被导入（与 portfolio_b1_small.py 用法一致）
_PROJECT_ROOT = settings.PROJECT_ROOT
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# b1_small 主板前缀
_MAIN_BOARD_PREFIXES = ("600", "000", "001")
# b1_small 价格上限
_B1_SMALL_MAX_PRICE = 100.0
# 默认并发 worker 数
_DEFAULT_WORKERS = 8


def _scan_worker(args: tuple) -> Optional[dict]:
    """进程池 worker：单只股票打分。
    放在模块顶层以保证可被 pickle，供 ProcessPoolExecutor 调用。
    """
    strategy_name, symbol, date = args
    try:
        from tests.scan_b1_full import check_one as scan_b1_check_one
        result = scan_b1_check_one((symbol, date))
        if result is None:
            return None
        if strategy_name == "b1_small" and float(result.get("close", 0)) > _B1_SMALL_MAX_PRICE:
            return None
        return result
    except Exception as e:
        logger.debug(f"扫描 {symbol} 失败: {e}")
        return None


class Scanner:
    """批量筛选引擎"""

    def __init__(self, strategy_name: str, stock_list: List[str]):
        """
        :param strategy_name: 策略名称（如 'b1_small'）
        :param stock_list: 股票代码列表（格式：sh.600000 或纯数字 600000）
        """
        self.strategy_name = strategy_name
        self.stock_list = stock_list
        self._st_set = self._load_st_set()

    def _load_st_set(self) -> set:
        path = os.path.join(settings.DATA_DIR, "stock_extra_info.json")
        if not os.path.exists(path):
            return set()
        try:
            with open(path, "r") as f:
                data = json.load(f)
            return {k for k, v in data.items() if v.get("is_st", False)}
        except Exception:
            return set()

    @staticmethod
    def _is_main_board(symbol: str) -> bool:
        return symbol.startswith(_MAIN_BOARD_PREFIXES)

    def scan(self, date: str, workers: int = _DEFAULT_WORKERS) -> List[dict]:
        """
        扫描全市场，返回候选股票列表（按评分降序）
        :param date: 扫描日期（YYYY-MM-DD）
        :param workers: 并发进程数，默认 8
        :return: 候选股票列表
        """
        # 前置过滤：归一化代码 + b1_small 主板/ST 过滤
        tasks = []
        for stock_code in self.stock_list:
            symbol = _normalize_stock_code(stock_code)
            if self.strategy_name == "b1_small":
                if not self._is_main_board(symbol):
                    continue
                if symbol in self._st_set:
                    continue
            tasks.append((self.strategy_name, symbol, date))

        candidates: List[dict] = []
        total = len(tasks)
        done = 0

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_scan_worker, t) for t in tasks]
            for fut in as_completed(futures):
                done += 1
                try:
                    result = fut.result()
                    if result:
                        candidates.append(result)
                except Exception as e:
                    logger.debug(f"worker 异常: {e}")
                if done % 500 == 0 or done == total:
                    logger.info(f"扫描进度 {done}/{total}，命中 {len(candidates)}")

        # 按评分降序排序（评分越高越优先）
        candidates.sort(key=lambda r: -int(r.get("score", 0)))

        logger.info(f"扫描完成: {len(candidates)} 只候选 / {total} 只参与扫描 / 共 {len(self.stock_list)} 只输入")
        return candidates

    def _check_stock(self, symbol: str, date: str) -> Optional[dict]:
        """单只股票检查（同 _scan_worker，保留供单元测试/调试调用）"""
        if self.strategy_name == "b1_small":
            if not self._is_main_board(symbol):
                return None
            if symbol in self._st_set:
                return None
        return _scan_worker((self.strategy_name, symbol, date))

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

    def save_to_selected(self, candidates: List[dict], date: str) -> str:
        """保存选股结果到 selected/{yyyy-mm-dd}/{strategy}.json"""
        from api.config.settings import PROJECT_ROOT
        folder_path = os.path.join(PROJECT_ROOT, "selected", date)
        os.makedirs(folder_path, exist_ok=True)

        result = {
            "scan_date": date,
            "strategy": self.strategy_name,
            "total_scanned": len(self.stock_list),
            "candidates_count": len(candidates),
            "candidates": candidates,
        }

        output_path = os.path.join(folder_path, f"{self.strategy_name}.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"选股结果已保存到 {output_path}")
        return output_path
