"""选股结果 API 路由"""
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import List, Dict, Any, Tuple

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
# (strategy, date) -> task_id  仅追踪 running 任务，用于去重
_running_index: Dict[Tuple[str, str], str] = {}
# 保护 _tasks 与 _running_index 的并发访问
_tasks_lock = threading.Lock()


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
    """异步执行选股扫描，立即返回 task_id。
    同 strategy + date 已在运行时复用已有任务，避免重复触发。
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    key = (strategy, date)
    with _tasks_lock:
        existing_id = _running_index.get(key)
        if existing_id is not None:
            existing = _tasks.get(existing_id)
            if existing and existing.get("status") == "running":
                logger.info(f"复用进行中的选股任务 {existing_id} ({strategy}/{date})")
                return {
                    "status": "running",
                    "task_id": existing_id,
                    "strategy": strategy,
                    "date": date,
                    "deduped": True,
                }
            # 状态不一致：清掉索引
            _running_index.pop(key, None)

        task_id = str(uuid.uuid4())[:8]
        _tasks[task_id] = {"status": "running", "strategy": strategy, "date": date}
        _running_index[key] = task_id

    thread = threading.Thread(target=_run_scan_worker, args=(task_id, strategy, date), daemon=True)
    thread.start()

    return {"status": "running", "task_id": task_id, "strategy": strategy, "date": date}


@router.get("/task/{task_id}")
def get_task_status(task_id: str) -> Dict[str, Any]:
    """查询异步选股任务状态"""
    task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


def _run_scan_worker(task_id: str, strategy: str, date: str):
    """后台线程执行选股"""
    from api.scanner.scanner import Scanner

    key = (strategy, date)
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
    except Exception as e:
        logger.error(f"选股任务 {task_id} 失败: {e}", exc_info=True)
        _tasks[task_id] = {"status": "error", "error": str(e),
                           "strategy": strategy, "date": date}
    finally:
        # 不论成功/失败都从 running 索引中移除，允许后续重新触发
        with _tasks_lock:
            if _running_index.get(key) == task_id:
                _running_index.pop(key, None)

