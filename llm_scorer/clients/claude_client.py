"""
Claude Opus 4.7 客户端
实现 LLMClient 接口，调用 Anthropic API 进行股票打分
"""
import base64
import json
import logging
import re
import time
from typing import List

from llm_scorer.clients.base import LLMClient

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-20250514"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TIMEOUT = 120
MAX_RETRIES = 2
RETRY_INTERVAL = 5


class ClaudeClient(LLMClient):
    """Claude Opus 4.7 客户端"""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)
        self.model = model

    def score_table(self, table: str, prompt: str, top_n: int) -> dict:
        full_prompt = prompt.replace("{markdown_table}", table)

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    messages=[{
                        "role": "user",
                        "content": [{"type": "text", "text": full_prompt}]
                    }]
                )
                text = response.content[0].text
                return self._parse_json_response(text)

            except Exception as e:
                logger.warning(f"阶段1 API调用失败 (第{attempt+1}次): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_INTERVAL)
                    continue
                logger.error(f"阶段1 API调用彻底失败: {e}")
                return {"top_n": []}

    def score_images(self, images: List[str], context: List[dict], prompt: str) -> dict:
        content = []

        # 添加每张图片
        for i, image_path in enumerate(images):
            try:
                image_data = self._read_image_base64(image_path)
                symbol = context[i]["symbol"] if i < len(context) else f"stock_{i}"

                content.append({"type": "text", "text": f"--- 股票 {symbol} ---"})
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_data,
                    }
                })
            except Exception as e:
                logger.warning(f"读取图片 {image_path} 失败: {e}")
                continue

        content.append({"type": "text", "text": prompt})

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=DEFAULT_MAX_TOKENS,
                    messages=[{"role": "user", "content": content}]
                )
                text = response.content[0].text
                return self._parse_json_response(text)

            except Exception as e:
                logger.warning(f"阶段2 API调用失败 (第{attempt+1}次): {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_INTERVAL)
                    continue
                logger.error(f"阶段2 API调用彻底失败: {e}")
                return {"results": []}

    def _read_image_base64(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
            return base64.standard_b64encode(f.read()).decode("utf-8")

    def _parse_json_response(self, text: str) -> dict:
        """解析 LLM 返回的 JSON，支持从混合文本中提取"""
        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 JSON 块
        patterns = [
            r'```json\s*([\s\S]*?)\s*```',  # ```json ... ```
            r'```\s*([\s\S]*?)\s*```',        # ``` ... ```
            r'(\{[\s\S]*\})',                  # 最外层 { ... }
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    continue

        logger.error(f"JSON 解析失败，原始响应: {text[:500]}")
        return {}
