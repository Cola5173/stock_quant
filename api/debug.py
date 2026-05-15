"""
快速启动 FastAPI 后端（开发模式 + 自动 reload）

用法：
    .venv/bin/python api/debug.py

或在 PyCharm / VSCode 直接 Run 这个文件即可。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        log_level="info",
    )
