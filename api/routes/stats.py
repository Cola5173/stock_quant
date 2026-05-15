"""首页统计接口"""
from fastapi import APIRouter

from api.schemas.models import HomeStats
from api.services.stats_service import get_home_stats

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats", response_model=HomeStats)
def stats():
    """首页概览统计：股票数 / 策略数 / 数据源数"""
    return get_home_stats()
