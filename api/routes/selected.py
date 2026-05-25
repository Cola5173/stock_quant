"""选股结果 API 路由"""
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, HTTPException

from api.config import settings
from api.services.selected_service import (
    list_strategies,
    list_records,
    get_record_detail,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/selected", tags=["selected"])

# 内存任务池（进程级，重启清空）
_tasks: Dict[str, Dict[str, Any]] = {}
# strategy -> 当前 running task_id（用于复用）
_running_task: Dict[str, str] = {}
# strategy -> 互斥锁（懒创建，每个策略独立一把锁）
_strategy_locks: Dict[str, threading.Lock] = {}

_tasks_lock = threading.Lock()      # 保护 _tasks / _running_task
_locks_lock = threading.Lock()      # 保护 _strategy_locks 字典本身


def _get_strategy_lock(strategy: str) -> threading.Lock:
    """懒创建并返回 strategy 维度的互斥锁。"""
    with _locks_lock:
        if strategy not in _strategy_locks:
            _strategy_locks[strategy] = threading.Lock()
        return _strategy_locks[strategy]


@router.get("/strategies")
def get_strategies() -> List[Dict[str, str]]:
    return list_strategies()


@router.get("/{strategy}/records")
def get_records(strategy: str) -> List[Dict[str, Any]]:
    return list_records(strategy)


@router.get("/{strategy}/{date}")
def get_detail(strategy: str, date: str) -> Dict[str, Any]:
    result = get_record_detail(strategy, date)
    if result is None:
        raise HTTPException(status_code=404, detail="未找到该日期的选股记录")
    return result


@router.post("/{strategy}/run")
def run_scan(strategy: str, date: str = None) -> Dict[str, Any]:
    """异步执行选股扫描。
    每个策略一把互斥锁：同策略已有任务在跑则复用，否则抢锁启动新任务。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    lock = _get_strategy_lock(strategy)
    # 抢锁；抢不到说明该策略已有任务在跑
    if not lock.acquire(blocking=False):
        with _tasks_lock:
            existing_id = _running_task.get(strategy)
            existing = _tasks.get(existing_id) if existing_id else None
        logger.info(f"策略 {strategy} 锁被占用，复用 task_id={existing_id}")
        return {
            "status": "running",
            "task_id": existing_id or "",
            "strategy": strategy,
            "date": (existing or {}).get("date", date),
            "deduped": True,
        }

    try:
        task_id = str(uuid.uuid4())[:8]
        with _tasks_lock:
            _tasks[task_id] = {"status": "running", "strategy": strategy, "date": date}
            _running_task[strategy] = task_id

        thread = threading.Thread(
            target=_run_scan_worker,
            args=(task_id, strategy, date, lock),
            daemon=True,
        )
        thread.start()
        logger.info(f"选股任务已启动 task_id={task_id} ({strategy}/{date})，锁由后台线程持有")
        return {"status": "running", "task_id": task_id, "strategy": strategy, "date": date}
    except Exception:
        lock.release()
        raise


@router.get("/task/{task_id}")
def get_task_status(task_id: str) -> Dict[str, Any]:
    """查询异步选股任务状态。

    如果内存中找不到任务（服务器重启/多 worker），尝试从文件系统推断状态：
    - 扫描 selected/ 目录，找最近 3 天内的结果文件
    - 如果找到匹配的策略结果，返回 done 状态
    - 否则返回 404
    """
    task = _tasks.get(task_id)
    if task is not None:
        return task

    # 内存中找不到，尝试从文件系统推断（容错：服务器重启/多 worker）
    # 扫描最近 3 天的 selected/{date}/ 目录
    from datetime import datetime, timedelta
    selected_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "selected"
    )
    if not os.path.isdir(selected_dir):
        raise HTTPException(404, "任务不存在且无法从文件推断")

    # 生成最近 3 天的日期列表
    today = datetime.now().date()
    dates = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]

    # 遍历所有策略，检查是否有最近的结果文件
    for date_str in dates:
        date_dir = os.path.join(selected_dir, date_str)
        if not os.path.isdir(date_dir):
            continue
        for strategy_file in os.listdir(date_dir):
            if not strategy_file.endswith(".json"):
                continue
            strategy = strategy_file.replace(".json", "")
            file_path = os.path.join(date_dir, strategy_file)
            # 检查文件修改时间是否在最近 10 分钟内（推断为刚完成的任务）
            if os.path.getmtime(file_path) > (datetime.now().timestamp() - 600):
                try:
                    import json
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    return {
                        "status": "done",
                        "strategy": strategy,
                        "date": date_str,
                        "candidates_count": data.get("candidates_count", 0),
                        "recovered": True,  # 标记为从文件恢复的状态
                    }
                except Exception:
                    pass

    raise HTTPException(404, "任务不存在且无法从文件推断")


def _run_scan_worker(task_id: str, strategy: str, date: str, lock: threading.Lock):
    """后台线程执行选股，finally 中释放锁。"""
    from api.scanner.scanner import Scanner

    try:
        stock_list_file = settings.STOCK_LIST_CACHE
        if not os.path.exists(stock_list_file):
            stock_list_file = settings.STOCK_CODE_FILE
        if not os.path.exists(stock_list_file):
            _tasks[task_id] = {"status": "error", "error": "未找到股票列表文件",
                               "strategy": strategy, "date": date}
            return

        stock_codes = []
        with open(stock_list_file, "r", encoding="utf-8-sig") as f:
            for line in f:
                code = line.strip()
                if code:
                    stock_codes.append(code)

        if not stock_codes:
            _tasks[task_id] = {"status": "error", "error": "股票列表为空",
                               "strategy": strategy, "date": date}
            return

        scanner = Scanner(strategy, stock_codes)
        candidates = scanner.scan(date)
        scanner.save_to_selected(candidates, date)

        _tasks[task_id] = {
            "status": "done",
            "strategy": strategy,
            "date": date,
            "candidates_count": len(candidates),
        }
        logger.info(f"选股任务完成 task_id={task_id} ({strategy}/{date}) 候选 {len(candidates)} 只")
    except Exception as e:
        logger.error(f"选股任务 {task_id} 失败: {e}", exc_info=True)
        _tasks[task_id] = {"status": "error", "error": str(e),
                           "strategy": strategy, "date": date}
    finally:
        with _tasks_lock:
            if _running_task.get(strategy) == task_id:
                _running_task.pop(strategy, None)
        lock.release()
        logger.info(f"策略 {strategy} 锁已释放")
