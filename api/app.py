"""FastAPI 入口"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

# 应用日志配置：uvicorn 只配自己的 access logger，应用代码里的 logger 默认丢弃
# force=True 覆盖任何已存在的 root handler，确保 api/* 的 logger.info 能输出
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    force=True,
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import stocks, backtest, stats, fetch, selected, advisor, portfolio_backtest

app = FastAPI(
    title="Cola Quant API",
    version="1.0.0",
    description="A 股量化回测平台后端",
)

# 前后端分离，开放 CORS（开发期允许所有源；生产环境收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)
app.include_router(backtest.router)
app.include_router(stats.router)
app.include_router(fetch.router)
app.include_router(selected.router)
app.include_router(advisor.router)
app.include_router(portfolio_backtest.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
