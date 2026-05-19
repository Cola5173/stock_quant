"""FastAPI 入口"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
