"""
LLM 客户端基类
定义打分接口，支持多模型扩展
"""
from abc import ABC, abstractmethod
from typing import List


class LLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    def score_table(self, table: str, prompt: str, top_n: int) -> dict:
        """
        阶段 1：表格初筛
        :param table: Markdown 格式的股票指标表格
        :param prompt: 完整的 Prompt 文本
        :param top_n: 返回 TOP N 数量
        :return: {"top_n": [{"rank": 1, "symbol": "600000", "score": 85, "reason": "..."}]}
        """
        pass

    @abstractmethod
    def score_images(self, images: List[str], context: List[dict], prompt: str) -> dict:
        """
        阶段 2：图形精筛
        :param images: K线图文件路径列表
        :param context: 候选股票上下文信息列表
        :param prompt: 完整的 Prompt 文本
        :return: {"results": [{"symbol": "600000", "score": 92, "recommendation": "...", ...}]}
        """
        pass
