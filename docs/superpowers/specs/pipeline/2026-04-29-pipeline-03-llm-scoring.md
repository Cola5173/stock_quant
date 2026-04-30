# 环节 3：LLM 两阶段打分

> 上游依赖：环节 2（筛选 + K线图生成）
> 下游消费：环节 4（组合回测 + 信号生成）
> 输入：`output/candidates/candidates_{date}.json`、`output/charts/*.png`
> 输出：`output/scores/scores_{date}.json`

## 1. 概述

两阶段筛选策略：
- **阶段 1（表格初筛）**：100 只候选股票的指标数据表格 → LLM 全局对比 → TOP 30
- **阶段 2（图形精筛）**：TOP 30 的 K 线图分 2 批（每批 15 张原图）→ LLM 深度分析 → TOP 10

## 2. 架构设计（可扩展多模型）

```python
from abc import ABC, abstractmethod

class LLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    def score_table(self, table: str, prompt: str, top_n: int) -> dict:
        """阶段 1：表格初筛"""
        pass

    @abstractmethod
    def score_images(self, images: List[str], context: List[dict], prompt: str) -> dict:
        """阶段 2：图形精筛（接收多张图片路径）"""
        pass


class ClaudeClient(LLMClient):
    """Claude Opus 4.7 客户端"""

    def __init__(self, api_key: str):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)

    def score_table(self, table, prompt, top_n):
        # 构建纯文本消息
        # 调用 Claude API
        # 解析 JSON 响应
        pass

    def score_images(self, images, context, prompt):
        # 读取多张图片并转为 base64
        # 构建多图消息
        # 调用 Claude API
        # 解析 JSON 响应
        pass


class GPTClient(LLMClient):
    """GPT-4o 客户端（后续扩展）"""
    pass
```

## 3. TwoStageScorer 核心类

```python
class TwoStageScorer:
    """两阶段分批筛选"""

    def __init__(self, client: LLMClient):
        self.client = client

    def score(self, candidates: List[dict]) -> List[dict]:
        # 阶段 1：表格全局筛选
        table = self._build_table(candidates)
        stage1_result = self.client.score_table(
            table=table,
            prompt=STAGE1_PROMPT,
            top_n=30
        )

        # 阶段 2：分批图形精筛
        top30 = [c for c in candidates if c["symbol"] in stage1_result.symbols]
        batch1 = top30[:15]
        batch2 = top30[15:]

        result1 = self.client.score_images(
            images=[self._get_chart(c) for c in batch1],
            context=batch1,
            prompt=STAGE2_PROMPT
        )

        result2 = self.client.score_images(
            images=[self._get_chart(c) for c in batch2],
            context=batch2,
            prompt=STAGE2_PROMPT
        )

        # 合并排序
        all_results = result1.results + result2.results
        all_results.sort(key=lambda x: x["score"], reverse=True)

        return all_results[:10]
```

## 4. Prompt 模板

### 4.1 阶段 1（表格初筛）

```
你是专业的A股技术分析师。以下是今日筛选出的{count}只候选股票的技术指标数据：

{markdown_table}

请根据以下标准进行初步筛选，选出最有潜力的TOP 30：

1. 趋势判断：白线 > 黄线（短期趋势向上）
2. KDJ位置：J值在10-30之间（低位但未超卖）
3. 价格位置：收盘价接近或高于白线（价格支撑强）
4. 振幅：近期振幅适中（2%-6%，活跃但不过度波动）

请严格按照以下 JSON 格式输出，不要添加任何解释文字：
{
  "top30": [
    {"rank": 1, "symbol": "600000", "score": 85, "reason": "..."},
    ...
  ]
}
```

### 4.2 阶段 2（图形精筛）

```
以下是初筛出的股票的K线图（每张图标注了股票代码）。

请深度分析K线形态、技术指标走势，选出最终TOP 10并给出详细评分：

重点关注：
1. K线形态（是否出现底部反转信号、多头排列等）
2. 趋势线走势（白线黄线的角度和间距）
3. KDJ指标形态（是否金叉、J值拐点）
4. 成交量配合（放量上涨、缩量回调）
5. 支撑阻力位（关键价位的突破或回踩）

请严格按照以下 JSON 格式输出，不要添加任何解释文字：
{
  "top10": [
    {
      "rank": 1,
      "symbol": "600000",
      "score": 92,
      "recommendation": "强烈买入",
      "analysis": {
        "pattern": "底部双底形态，颈线突破...",
        "trend": "白线上穿黄线，多头趋势确立...",
        "kdj": "J值从低位拐头向上，金叉形成...",
        "volume": "突破时放量，回踩缩量，健康...",
        "support": "支撑位8.30，目标位9.50..."
      },
      "prediction": {
        "target_price": 9.50,
        "expected_return": 11.5,
        "time_horizon": "2-3周"
      }
    }
  ]
}
```

## 5. 输出格式

```json
// output/scores/scores_20260429.json
{
  "score_date": "2026-04-29",
  "model": "claude-opus-4-20250514",
  "total_scored": 87,
  "stage1_top30": [
    {"rank": 1, "symbol": "600000", "score": 85, "reason": "..."}
  ],
  "final_top10": [
    {
      "rank": 1,
      "symbol": "600000",
      "score": 92,
      "recommendation": "强烈买入",
      "analysis": {...},
      "prediction": {...}
    }
  ]
}
```

## 6. 错误处理

**重试策略：**
- 2 次重试，固定间隔 5 秒
- 超时设置：60 秒

**降级方案：**
- 阶段 1 失败：使用指标排序（KDJ J 值 + 白线/黄线比值）
- 阶段 2 失败：使用阶段 1 的 TOP 30 结果
- 记录失败原因和原始响应到 `logs/llm_error.log`

**JSON 解析失败时：**
- 使用正则提取 JSON 部分：`r'\{[\s\S]*\}'`
- 如果仍失败，记录原始响应并使用降级方案

## 7. CLI 命令

```bash
python main.py score --date 2026-04-29 --model claude
# 输出: output/scores/scores_20260429.json
```
