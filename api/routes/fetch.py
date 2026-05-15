"""数据拉取接口"""
from fastapi import APIRouter, Query

from api.schemas.models import FetchStatus, FetchTriggerResponse
from api.services.fetch_service import start_fetch_latest, get_status

router = APIRouter(prefix="/api/fetch", tags=["fetch"])


@router.post("/latest", response_model=FetchTriggerResponse)
def trigger_fetch(source: str = Query("tushare", description="数据源")):
    """触发后台拉取任务（异步），增量拉取每只股票到今天的最新数据"""
    started = start_fetch_latest(source)
    if not started:
        return FetchTriggerResponse(started=False, message="已有拉取任务在运行，请稍后")
    return FetchTriggerResponse(started=True, message=f"已启动 {source} 拉取任务（后台运行）")


@router.get("/status", response_model=FetchStatus)
def fetch_status():
    """查询当前拉取任务状态"""
    return get_status()
