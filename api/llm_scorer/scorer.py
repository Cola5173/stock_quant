"""
两阶段打分引擎
阶段1：表格初筛（100 -> 30）
阶段2：图形精筛（30 -> 10，分2批）
"""
import json
import logging
import os
from typing import List

from api.config import settings
from api.llm_scorer.clients.base import LLMClient
from api.llm_scorer.prompts import STAGE1_PROMPT, STAGE2_PROMPT

logger = logging.getLogger(__name__)


class TwoStageScorer:
    """两阶段分批筛选"""

    def __init__(self, client: LLMClient):
        self.client = client

    def score(self, candidates: List[dict], date: str) -> dict:
        """
        执行两阶段打分
        :param candidates: 候选股票列表
        :param date: 日期（YYYY-MM-DD）
        :return: 打分结果字典
        """
        logger.info(f"开始两阶段打分: {len(candidates)} 只候选")

        # 阶段 1：表格初筛
        logger.info("阶段1: 表格初筛...")
        table = self._build_table(candidates)
        stage1_result = self.client.score_table(table, STAGE1_PROMPT, 30)

        top30_symbols = [item["symbol"] for item in stage1_result.get("top30", [])]
        if not top30_symbols:
            logger.warning("阶段1 未返回结果，使用降级方案（指标排序）")
            top30_symbols = self._fallback_stage1(candidates)

        logger.info(f"阶段1 完成: TOP 30 = {top30_symbols[:5]}...")

        # 阶段 2：分批图形精筛
        logger.info("阶段2: 图形精筛...")
        top30 = [c for c in candidates if c["symbol"] in top30_symbols]
        if len(top30) < len(top30_symbols):
            logger.warning(f"部分股票未找到K线图: {len(top30)}/{len(top30_symbols)}")

        batch1 = top30[:15]
        batch2 = top30[15:]

        result1 = self._score_batch(batch1, date, "batch1")
        result2 = self._score_batch(batch2, date, "batch2") if batch2 else {"top10": []}

        # 合并排序
        all_results = result1.get("top10", []) + result2.get("top10", [])
        if not all_results:
            logger.warning("阶段2 未返回结果，使用降级方案（阶段1 TOP 10）")
            all_results = self._fallback_stage2(stage1_result)

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        final_top10 = all_results[:10]

        logger.info(f"阶段2 完成: TOP 10 = {[r['symbol'] for r in final_top10]}")

        return {
            "score_date": date,
            "model": getattr(self.client, "model", "unknown"),
            "total_scored": len(candidates),
            "stage1_top30": stage1_result.get("top30", []),
            "final_top10": final_top10,
        }

    def _build_table(self, candidates: List[dict]) -> str:
        """构建 Markdown 表格"""
        lines = ["| 编号 | 代码 | 名称 | 收盘价 | KDJ_J | 白线 | 黄线 | 振幅 |"]
        lines.append("|------|------|------|--------|-------|------|------|------|")

        for i, c in enumerate(candidates, 1):
            ind = c.get("indicators", {})
            lines.append(
                f"| {i} | {c['symbol']} | {c.get('name', c['symbol'])} | "
                f"{c.get('close', 0):.2f} | {ind.get('kdj_j', 0):.2f} | "
                f"{ind.get('zx_white', 0):.2f} | {ind.get('zx_yellow', 0):.2f} | "
                f"{ind.get('amplitude', 0):.2f}% |"
            )

        return "\n".join(lines)

    def _score_batch(self, batch: List[dict], date: str, batch_name: str) -> dict:
        """对一批股票进行图形打分"""
        if not batch:
            return {"top10": []}

        date_str = date.replace("-", "")
        images = []
        for c in batch:
            chart_path = os.path.join(settings.CHARTS_DIR, f"{c['symbol']}_{date_str}.png")
            if os.path.exists(chart_path):
                images.append(chart_path)
            else:
                logger.warning(f"K线图不存在: {chart_path}")

        if not images:
            logger.warning(f"{batch_name} 无可用K线图")
            return {"top10": []}

        logger.info(f"{batch_name}: {len(images)} 张K线图")
        return self.client.score_images(images, batch, STAGE2_PROMPT)

    def _fallback_stage1(self, candidates: List[dict]) -> List[str]:
        """阶段1 降级方案：按 KDJ J 值 + 白线/黄线比值排序"""
        scored = []
        for c in candidates:
            ind = c.get("indicators", {})
            j = ind.get("kdj_j", 50)
            white = ind.get("zx_white", 0)
            yellow = ind.get("zx_yellow", 1)
            ratio = white / yellow if yellow > 0 else 1
            # J 值越低越好，白线/黄线比值越大越好
            score = (30 - j) * 2 + (ratio - 1) * 100
            scored.append((c["symbol"], score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored[:30]]

    def _fallback_stage2(self, stage1_result: dict) -> List[dict]:
        """阶段2 降级方案：使用阶段1 的 TOP 10"""
        top30 = stage1_result.get("top30", [])
        return [
            {
                "rank": i + 1,
                "symbol": item["symbol"],
                "score": item.get("score", 0),
                "recommendation": "待确认",
                "analysis": {"pattern": "降级方案，未进行图形分析"},
                "prediction": {},
            }
            for i, item in enumerate(top30[:10])
        ]

    def save_result(self, result: dict, date: str) -> str:
        """保存打分结果到 JSON"""
        os.makedirs(settings.SCORES_DIR, exist_ok=True)
        date_str = date.replace("-", "")
        output_path = os.path.join(settings.SCORES_DIR, f"scores_{date_str}.json")

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        logger.info(f"打分结果已保存到 {output_path}")
        return output_path
