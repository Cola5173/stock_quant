"""策略回测接口"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from glob import glob

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.config import settings

router = APIRouter(prefix="/api/portfolio-backtest", tags=["portfolio_backtest"])

# 策略元信息
STRATEGY_META = {
    "b1_small": {
        "key": "b1_small",
        "label": "B1 小资金（20w）",
        "script": "tests/portfolio_b1_small.py",
        "description": [
            "选股：B1 真实选股逻辑（异动突破 + 多因子打分）",
            "仅主板（600/000/001 开头），价格 ≤ 100 元",
            "强市最多 2 只（单只 50%），弱市最多 1 只（单只 40%）",
            "硬止损：弱市 -3%，强市 -5%",
            "时间止损 T+5：5 个交易日内涨幅 < 2.5% 即卖",
            "分批止盈：+8% / +16% / +24%",
            "连续 2 笔亏损后冷却 10 日",
        ],
    },
    "b1_top2": {
        "key": "b1_top2",
        "label": "B1 Top-2（v2 高周转）",
        "script": "tests/portfolio_b1_top2.py",
        "description": [
            "每日扫描全市场，Top-2 评分最高，T+1 开盘等额买入",
            "单只股票最大仓位 50%",
            "硬止损：弱市 -4%，强市 -7%",
            "时间止损 T+3：涨幅 < 2% 即卖",
            "9 级分批止盈：每涨 +10% 卖 1/3，最高 +90%",
            "大盘跌破长均线，禁止买入",
        ],
    },
}


class BacktestRunRequest(BaseModel):
    strategy: str
    start: str
    end: str
    capital: float = 200000


@router.get("/strategies")
def list_strategies():
    """返回可选策略列表"""
    return list(STRATEGY_META.values())


@router.get("/runs")
def list_runs():
    """列出所有历史回测结果（按时间倒序）。
    新文件名：{yyyy-mm-dd}-{strategy}.json （执行日期）
    旧文件名：{strategy}_{start}_{end}.json （保留向后兼容）
    """
    pattern = os.path.join(settings.PORTFOLIO_DIR, "*.json")
    new_name_re = re.compile(r"^(\d{4}-\d{2}-\d{2})-(b1_small|b1_top2)\.json$")
    old_name_re = re.compile(r"^(b1_small|b1_top2|small_capital)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.json$")
    runs = []
    for path in glob(pattern):
        filename = os.path.basename(path)
        strategy_key = None
        start = end = None

        m_new = new_name_re.match(filename)
        if m_new:
            strategy_key = m_new.group(2)
        else:
            m_old = old_name_re.match(filename)
            if not m_old:
                continue
            strategy_key, start, end = m_old.group(1), m_old.group(2), m_old.group(3)
            if strategy_key == "small_capital":
                strategy_key = "b1_small"

        try:
            stat = os.stat(path)
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stats = data.get("stats", {})
            # 新命名没把 start/end 编进文件名，从 JSON 的 period 字段读
            if start is None or end is None:
                period = data.get("period", {})
                start = period.get("start") or start
                end = period.get("end") or end
            runs.append({
                "id": filename,
                "strategy_key": strategy_key,
                "strategy_label": STRATEGY_META.get(strategy_key, {}).get("label", strategy_key),
                "run_time": mtime,
                "start": start,
                "end": end,
                "total_return_pct": stats.get("total_return_pct", 0),
                "annual_return_pct": stats.get("annual_return_pct", 0),
                "max_drawdown_pct": stats.get("max_drawdown_pct", 0),
                "win_rate_pct": stats.get("win_rate_pct", 0),
                "trades_closed": stats.get("trades_closed", 0),
            })
        except Exception:
            continue

    runs.sort(key=lambda r: r["run_time"], reverse=True)
    return runs


@router.get("/runs/{run_id}")
def get_run_detail(run_id: str):
    """获取指定回测的详细数据"""
    # 安全：只允许 .json 文件，禁止路径穿越
    if "/" in run_id or ".." in run_id or not run_id.endswith(".json"):
        raise HTTPException(400, "非法的 run_id")
    path = os.path.join(settings.PORTFOLIO_DIR, run_id)
    if not os.path.exists(path):
        raise HTTPException(404, "未找到该回测记录")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 解析策略 key：先尝试新命名，再 fallback 旧命名
    strategy_key = "unknown"
    m_new = re.match(r"^\d{4}-\d{2}-\d{2}-(b1_small|b1_top2)\.json$", run_id)
    if m_new:
        strategy_key = m_new.group(1)
    else:
        m_old = re.match(r"^(b1_small|b1_top2|small_capital)_", run_id)
        if m_old:
            strategy_key = m_old.group(1)
            if strategy_key == "small_capital":
                strategy_key = "b1_small"
    data["strategy_key"] = strategy_key
    data["strategy_meta"] = STRATEGY_META.get(strategy_key, {})
    data["id"] = run_id
    return data


@router.post("/run")
def run_backtest(req: BacktestRunRequest, background_tasks: BackgroundTasks):
    """触发新的回测（后台执行）。
    结果文件名：{执行日期 yyyy-mm-dd}-{strategy}.json，同日重复执行会覆盖。
    """
    if req.strategy not in STRATEGY_META:
        raise HTTPException(400, f"未知策略: {req.strategy}")
    meta = STRATEGY_META[req.strategy]
    script = os.path.join(settings.PROJECT_ROOT, meta["script"])
    if not os.path.exists(script):
        raise HTTPException(500, f"脚本不存在: {script}")

    exec_date = datetime.now().strftime("%Y-%m-%d")
    out_path = os.path.join(
        settings.PORTFOLIO_DIR,
        f"{exec_date}-{req.strategy}.json"
    )
    log_path = os.path.join(
        settings.PORTFOLIO_DIR,
        f".running_{exec_date}-{req.strategy}.log"
    )

    def _run():
        os.makedirs(settings.PORTFOLIO_DIR, exist_ok=True)
        # 标记为运行中
        with open(log_path, "w") as f:
            f.write(f"started at {datetime.now()}\n")
        cmd = [
            sys.executable, script,
            "--start", req.start,
            "--end", req.end,
            "--capital", str(req.capital),
            "--workers", "8",
            "--out", out_path,
        ]
        try:
            with open(log_path, "a") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=settings.PROJECT_ROOT, timeout=1800)
        finally:
            if os.path.exists(log_path):
                os.unlink(log_path)

    background_tasks.add_task(_run)
    return {"status": "started", "out_path": out_path}


@router.get("/running")
def list_running():
    """查询当前正在运行的回测任务"""
    pattern = os.path.join(settings.PORTFOLIO_DIR, ".running_*.log")
    new_re = re.compile(r"^\.running_(\d{4}-\d{2}-\d{2})-(b1_small|b1_top2)\.log$")
    old_re = re.compile(r"^\.running_(b1_small|b1_top2)_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.log$")
    running = []
    for path in glob(pattern):
        filename = os.path.basename(path)
        m_new = new_re.match(filename)
        if m_new:
            running.append({
                "strategy_key": m_new.group(2),
                "exec_date": m_new.group(1),
            })
            continue
        m_old = old_re.match(filename)
        if m_old:
            running.append({
                "strategy_key": m_old.group(1),
                "start": m_old.group(2),
                "end": m_old.group(3),
            })
    return running
