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
    """查询异步选股任务状态"""
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


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
