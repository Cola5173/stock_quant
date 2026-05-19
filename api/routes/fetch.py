"""数据拉取接口"""
from fastapi import APIRouter, Query

from api.schemas.models import FetchStatus, FetchTriggerResponse
from api.services.fetch_service import start_fetch_latest, get_status

router = APIRouter(prefix="/api/fetch", tags=["fetch"])


@router.post("/latest", response_model=FetchTriggerResponse)
def trigger_fetch(source: str = Query("akshare", description="数据源")):
    """触发后台拉取任务（异步），增量拉取每只股票到今天的最新数据。
    复用规则：
    - 已有任务在跑 → started=False，复用进行中的任务
    - 标杆股本地数据已 ≥ 目标交易日 → started=False，直接复用最新结果，不再发起请求
    """
    res = start_fetch_latest(source)
    target = res.get("target_date") or "-"
    if res["reason"] == "running":
        return FetchTriggerResponse(
            started=False,
            message=f"已有拉取任务在运行（目标交易日 {target}），将复用现有结果",
        )
    if res["reason"] == "up_to_date":
        return FetchTriggerResponse(
            started=False,
            message=f"本地数据已是最新（目标交易日 {target}），无需重复拉取",
        )
    return FetchTriggerResponse(
        started=True,
        message=f"已启动 {source} 拉取任务（目标交易日 {target}，后台并发运行）",
    )


@router.get("/status", response_model=FetchStatus)
def fetch_status():
    """查询当前拉取任务状态"""
    return get_status()
